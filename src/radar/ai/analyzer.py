from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from radar.models import LLMAnalysis, RankedItem


SYSTEM_PROMPT = """你是 Research Engineer Radar 的技术编辑与工程导师。
你的任务不是总结新闻，也不是强行证明一条信息与用户当前项目相关，而是判断它是否值得一个 AI Research Engineer 花时间阅读。

优先寻找：
1. 可迁移的方法论：性能瓶颈定位、实验设计、benchmark、observability、成本/延迟优化、故障分析、可靠性设计。
2. AI/Python 系统性能工程：profiling、GPU utilization、batching、caching、I/O、memory、serving、latency、throughput。
3. Agent Engineering：从 Demo 到可运行、可靠、可评测、可观测、可恢复、可部署的完整工程，包括 planner/router/tool use/context/memory/evaluation/trace/retry/checkpoint/security/cost。
4. 前沿技术：OpenAI/Anthropic/Google 等的 Agent 工程设计、AI Infra 新工具、新型时序预测方法。

判断原则：
- 更看重“测量→定位→假设→优化→验证”的闭环，而不是技巧罗列。
- 更看重真实 trade-off、failure mode、benchmark、evaluation、observability、production experience。
- 允许明确判断“与当前项目无直接关系”；当前项目只作为可选应用案例，不是价值前提。
- 如果相关性需要超过一步推理才能建立，就不要强行建立联系。
- Demo-only、营销、浅教程、无评测的发布应降低评价。
- 只返回 JSON，不要 Markdown。"""

JSON_RE = re.compile(r"\{.*\}", re.S)
ACTIONS = {"精读", "浏览", "收藏", "尝试", "跳过"}
CATEGORIES = {"方法论", "性能工程", "Agent Engineering", "前沿技术", "时序预测", "其他"}


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
    category = str(payload.get("category", "其他")).strip() or "其他"
    if category not in CATEGORIES:
        category = "其他"
    return LLMAnalysis(
        long_term_value=_scale_score(payload.get("long_term_value", payload.get("relevance"))),
        methodology_value=_scale_score(payload.get("methodology_value")),
        engineering_depth=_scale_score(payload.get("engineering_depth", payload.get("engineering_value"))),
        production_value=_scale_score(payload.get("production_value")),
        transferability=_scale_score(payload.get("transferability", payload.get("project_transferability"))),
        novelty=_scale_score(payload.get("novelty")),
        actionability=_scale_score(payload.get("actionability")),
        category=category,
        core_problem=str(payload.get("core_problem", payload.get("what_it_is", ""))).strip(),
        key_takeaway=str(payload.get("key_takeaway", payload.get("why_it_matters", ""))).strip(),
        design_tradeoff=str(payload.get("design_tradeoff", "")).strip(),
        maturity_signal=str(payload.get("maturity_signal", "")).strip(),
        when_to_recall=str(payload.get("when_to_recall", payload.get("ability_tree_relation", ""))).strip(),
        agent_insight=str(payload.get("agent_insight", "")).strip(),
        performance_insight=str(payload.get("performance_insight", "")).strip(),
        current_project_relation=str(payload.get("current_project_relation", "")).strip(),
        suggested_action=action,
        experiment_idea=str(payload.get("experiment_idea", "")).strip(),
    )


def _post_chat(base_url: str, api_key: str, model: str, messages: list[dict], timeout: int) -> str:
    body = {"model": model, "temperature": 0.15, "messages": messages}
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
        "radar_focus": config.get("radar_focus", {}),
        "user_profile": config.get("user_profile", {}),
        "item": {
            "title": item.title,
            "source": item.source,
            "url": item.url,
            "summary": item.summary[:6500],
            "tags": item.tags[:12],
            "raw": {key: item.raw.get(key) for key in ["stars", "language", "topics", "license", "hn_score", "categories"] if key in item.raw},
        },
        "deterministic": {
            "score": row.score,
            "reasons": row.reasons[:10],
            "component_scores": row.component_scores,
        },
        "required_output": {
            "category": "只能是 方法论/性能工程/Agent Engineering/前沿技术/时序预测/其他 之一",
            "long_term_value": "0-10；三个月后是否仍有用",
            "methodology_value": "0-10；是否教会如何思考、测量、设计或判断",
            "engineering_depth": "0-10；是否有机制、实现细节和工程深度",
            "production_value": "0-10；是否涉及可靠性、评测、可观测性、成本、部署、故障或真实生产经验",
            "transferability": "0-10；能否迁移到不同 AI/科研工程问题，而非只适用于单一项目",
            "novelty": "0-10",
            "actionability": "0-10",
            "core_problem": "一句话：它真正解决的是什么问题",
            "key_takeaway": "一到两句：最值得带走的方法、设计思想或判断框架",
            "design_tradeoff": "如有，说明关键 trade-off；没有就空字符串",
            "maturity_signal": "指出 benchmark/evaluation/observability/failure analysis/production evidence；没有就明确说不足",
            "when_to_recall": "以后遇到什么类型的问题时应该想起它",
            "agent_insight": "仅 Agent 内容填写：对 Demo→可靠可落地 Agent 的启发；否则空字符串",
            "performance_insight": "仅性能内容填写：如何定位瓶颈并验证优化；否则空字符串",
            "current_project_relation": "可选。只有明显直接相关才写；否则必须写‘无明显直接关联’",
            "suggested_action": "只能是 精读/浏览/收藏/尝试/跳过 之一",
            "experiment_idea": "只有存在清晰的 20-60 分钟最小实验时才写；否则空字符串",
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

    deterministic_weight = float(llm_cfg.get("deterministic_weight", 0.40))
    llm_weight = float(llm_cfg.get("llm_weight", 0.60))
    total_weight = deterministic_weight + llm_weight or 1.0
    deterministic_weight /= total_weight
    llm_weight /= total_weight
    timeout = int(llm_cfg.get("timeout_seconds", 55))
    retries = int(llm_cfg.get("analysis_retries", 1))

    for row in items:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(_item_prompt(row, config), ensure_ascii=False)},
        ]
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                content = _post_chat(base_url, api_key, model, messages, timeout)
                analysis = parse_analysis(content)
                row.llm = analysis
                row.action = analysis.suggested_action
                row.score = round(row.score * deterministic_weight + analysis.score * llm_weight, 4)
                row.reasons.append(f"llm_value:{analysis.score:.2f}")
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                retryable = not isinstance(exc, HTTPError) or exc.code in {408, 429, 500, 502, 503, 504}
                if attempt >= retries or not retryable:
                    break
                time.sleep(1.25 * (attempt + 1))
        if last_error is not None:
            row.reasons.append("llm_fallback")
            print(f"[radar] LLM analysis failed for {row.item.title!r}: {last_error}")

    items.sort(key=lambda value: value.score, reverse=True)
    return items
