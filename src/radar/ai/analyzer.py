from __future__ import annotations

import json
import os
import re
from urllib.request import Request, urlopen

from radar.models import LLMAnalysis, RankedItem


SYSTEM_PROMPT = """你是 Research Engineer Radar 的二次筛选器。目标不是总结新闻，而是判断一条信息对 AI Research Engineer 成长是否真正有价值。
重点关注 AI/ML Systems、性能分析、训练/推理、数据流水线、评测、MLOps、AI Infra、Agent Engineering、Research Engineering、时序/电力预测的可迁移方法。
避免追逐纯热度、纯营销、没有工程细节的模型发布。只返回 JSON，不要 Markdown。"""

JSON_RE = re.compile(r"\{.*\}", re.S)
ACTIONS = {"精读", "浏览", "收藏", "尝试"}


def _endpoint(base_url: str, suffix: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith(suffix):
        return value
    if value.endswith("/chat/completions") and suffix == "/models":
        return value[: -len("/chat/completions")] + suffix
    return value + suffix


def _chat_endpoint(base_url: str) -> str:
    return _endpoint(base_url, "/chat/completions")


def _models_endpoint(base_url: str) -> str:
    return _endpoint(base_url, "/models")


def _scale_score(value: object) -> float:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return 0.0
    if raw > 1.0:
        raw = raw / 10.0
    return max(0.0, min(raw, 1.0))


def extract_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = JSON_RE.search(text)
        if not match:
            raise
        return json.loads(match.group(0))


def parse_analysis(content: str) -> LLMAnalysis:
    payload = extract_json_object(content)
    action = str(payload.get("suggested_action", payload.get("action", "浏览"))).strip() or "浏览"
    if action not in ACTIONS:
        action = "浏览"
    return LLMAnalysis(
        relevance=_scale_score(payload.get("relevance", payload.get("relevance_score"))),
        engineering_value=_scale_score(payload.get("engineering_value")),
        novelty=_scale_score(payload.get("novelty")),
        actionability=_scale_score(payload.get("actionability")),
        project_transferability=_scale_score(payload.get("project_transferability")),
        what_it_is=str(payload.get("what_it_is", payload.get("what", ""))).strip(),
        why_it_matters=str(payload.get("why_it_matters", payload.get("why", ""))).strip(),
        ability_tree_relation=str(payload.get("ability_tree_relation", payload.get("capability_relation", ""))).strip(),
        current_project_relation=str(payload.get("current_project_relation", payload.get("project_relation", ""))).strip(),
        suggested_action=action,
        experiment_idea=str(payload.get("experiment_idea", "")).strip(),
    )


def _post_chat(base_url: str, api_key: str, model: str, messages: list[dict], timeout: int) -> str:
    body = {"model": model, "temperature": 0.2, "messages": messages}
    request = Request(
        _chat_endpoint(base_url),
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


def check_llm_models(base_url: str, api_key: str, timeout: int = 15) -> bool:
    request = Request(_models_endpoint(base_url), headers={"Authorization": f"Bearer {api_key}"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return bool(payload.get("data") or payload.get("object"))


def check_llm_chat(base_url: str, api_key: str, model: str, timeout: int = 20) -> bool:
    content = _post_chat(
        base_url,
        api_key,
        model,
        [{"role": "user", "content": "Respond only with: RADAR_OK"}],
        timeout,
    )
    return "RADAR_OK" in content


def _item_prompt(row: RankedItem, config: dict) -> dict:
    item = row.item
    return {
        "user_profile": config.get("user_profile", {}),
        "item": {
            "title": item.title,
            "source": item.source,
            "url": item.url,
            "summary": item.summary[:6000],
            "tags": item.tags[:12],
            "raw": {key: item.raw.get(key) for key in ["stars", "language", "topics", "license", "hn_score", "categories"] if key in item.raw},
        },
        "deterministic": {
            "score": row.score,
            "reasons": row.reasons[:10],
            "component_scores": row.component_scores,
        },
        "required_output": {
            "relevance": "0-10",
            "engineering_value": "0-10",
            "novelty": "0-10",
            "actionability": "0-10",
            "project_transferability": "0-10",
            "what_it_is": "一句到两句说明这是什么",
            "why_it_matters": "为什么值得看，必须具体",
            "ability_tree_relation": "和 AI Research Engineer 能力树的关系",
            "current_project_relation": "和当前电力/时序预测、模型融合、尖峰预测、在线学习、性能优化项目的关系；没有就明确说弱相关",
            "suggested_action": "只能是 精读/浏览/收藏/尝试 之一",
            "experiment_idea": "只有确实能做最小实验时才写；否则留空",
        },
    }


def analyze_shortlist(items: list[RankedItem], config: dict) -> list[RankedItem]:
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled", False) or not items:
        return items

    api_key = os.getenv(llm_cfg.get("api_key_env", "LLM_API_KEY"), "")
    base_url = os.getenv(llm_cfg.get("base_url_env", "LLM_BASE_URL"), llm_cfg.get("base_url", ""))
    model = os.getenv(llm_cfg.get("model_env", "LLM_MODEL"), llm_cfg.get("model", ""))
    if not api_key or not base_url or not model:
        print("[radar] LLM enabled but configuration is incomplete; deterministic fallback is used.")
        return items

    deterministic_weight = float(llm_cfg.get("deterministic_weight", 0.45))
    llm_weight = float(llm_cfg.get("llm_weight", 0.55))
    total_weight = deterministic_weight + llm_weight or 1.0
    deterministic_weight /= total_weight
    llm_weight /= total_weight
    timeout = int(llm_cfg.get("timeout_seconds", 45))

    for row in items:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(_item_prompt(row, config), ensure_ascii=False)},
        ]
        try:
            content = _post_chat(base_url, api_key, model, messages, timeout)
            analysis = parse_analysis(content)
            row.llm = analysis
            row.action = analysis.suggested_action
            row.score = round(row.score * deterministic_weight + analysis.score * llm_weight, 4)
            row.reasons.append(f"llm_value:{analysis.score:.2f}")
        except Exception as exc:
            row.reasons.append("llm_fallback")
            print(f"[radar] LLM analysis failed for {row.item.title!r}: {exc}")

    items.sort(key=lambda value: value.score, reverse=True)
    return items
