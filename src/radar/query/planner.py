from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from radar.ai.analyzer import _post_chat, extract_json_object


PLANNER_SYSTEM_PROMPT = """你是 Research Navigator 的 Query Planner。用户会用自然语言描述想找的信息。
你的任务不是回答问题，而是把自然语言转成可执行的研究计划。

必须同时考虑：topic、intent、时间范围、关键词扩展、搜索子查询、平台、是否优先一手来源、是否需要沿链接/引用继续深挖。
优先理解用户真正想解决的问题，而不是机械提取原句关键词。

intent 只能是：latest / hot / primary_sources / deep_research / source_trace / compare / explain / general_search。
platforms 可从 web, arxiv, github, hacker_news, x, youtube 中选择。
如果用户说“最近/最新/热点”，默认 7 天；“今天”1天；“最近一个月”30天；没有时间要求默认30天。
如果用户强调源头、一手、官方、作者原帖，把 primary_only 设为 true。
如果用户说深挖、追溯、顺着链接找、来源链，把 depth 设为 2 或 3；普通搜索 depth=1。
搜索子查询要覆盖同义词、工程术语和英文术语，最多6个。
只返回 JSON，不要 Markdown。"""


@dataclass(slots=True)
class QueryPlan:
    original_query: str
    topic: str
    intent: str = "general_search"
    timeframe_days: int = 30
    keywords: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: ["web", "arxiv", "github", "hacker_news"])
    primary_only: bool = False
    depth: int = 1
    rationale: str = ""


def _fallback_plan(text: str) -> QueryPlan:
    lowered = text.lower()
    days = 30
    if any(token in text for token in ["今天", "今日", "24小时", "24 小时"]):
        days = 1
    elif any(token in text for token in ["最近一周", "近一周", "7天", "7 天"]):
        days = 7
    elif any(token in text for token in ["最近一个月", "近一个月", "30天", "30 天"]):
        days = 30
    elif any(token in text for token in ["最近", "最新", "热点", "热门"]):
        days = 7

    intent = "general_search"
    if any(token in text for token in ["源头", "来源链", "追溯", "一手", "官方"]):
        intent = "source_trace"
    elif any(token in text for token in ["深挖", "深入", "继续找", "顺着"]):
        intent = "deep_research"
    elif any(token in text for token in ["最新", "最近"]):
        intent = "latest"
    elif any(token in text for token in ["热点", "热门", "为什么突然"]):
        intent = "hot"

    depth = 2 if intent in {"source_trace", "deep_research"} else 1
    primary_only = any(token in text for token in ["一手", "官方", "源头", "作者原帖"])
    words = [w for w in re.split(r"[\s,，。！？;；:：()（）]+", text) if len(w) > 1]
    keywords = words[:8]
    platforms = ["web", "arxiv", "github", "hacker_news"]
    if any(token in lowered for token in ["twitter", "x.com", "推特", "x 上", "x上"]):
        platforms.append("x")
    if any(token in lowered for token in ["youtube", "油管", "视频", "演讲"]):
        platforms.append("youtube")
    return QueryPlan(
        original_query=text,
        topic=text.strip()[:120],
        intent=intent,
        timeframe_days=days,
        keywords=keywords,
        queries=[text.strip()],
        platforms=list(dict.fromkeys(platforms)),
        primary_only=primary_only,
        depth=depth,
        rationale="fallback",
    )


def _llm_settings(config: dict) -> tuple[str, str, str, int]:
    llm_cfg = config.get("llm", {})
    api_key = os.getenv(llm_cfg.get("api_key_env", "LLM_API_KEY"), "")
    base_url = os.getenv(llm_cfg.get("base_url_env", "LLM_BASE_URL"), llm_cfg.get("base_url", ""))
    model = os.getenv(llm_cfg.get("model_env", "LLM_MODEL"), llm_cfg.get("model", ""))
    timeout = min(int(llm_cfg.get("timeout_seconds", 55)), 35)
    return api_key, base_url, model, timeout


def plan_query(text: str, config: dict, history: list[dict] | None = None) -> QueryPlan:
    fallback = _fallback_plan(text)
    api_key, base_url, model, timeout = _llm_settings(config)
    if not (api_key and base_url and model):
        return fallback

    payload = {
        "user_query": text,
        "recent_conversation": (history or [])[-6:],
        "radar_focus": config.get("radar_focus", {}),
        "required_output": {
            "topic": "一句话归一化主题",
            "intent": "latest/hot/primary_sources/deep_research/source_trace/compare/explain/general_search",
            "timeframe_days": "1-90整数",
            "keywords": "用于相关性判断的关键词数组，最多10个",
            "queries": "用于搜索引擎的查询数组，最多6个，中英文可混合",
            "platforms": "web/arxiv/github/hacker_news/x/youtube 的子集",
            "primary_only": "boolean",
            "depth": "1-3整数",
            "rationale": "一句话说明为什么这样拆解",
        },
    }
    try:
        content = _post_chat(
            base_url,
            api_key,
            model,
            [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            timeout,
        )
        data = extract_json_object(content)
        topic = str(data.get("topic") or fallback.topic).strip()[:160]
        intent = str(data.get("intent") or fallback.intent).strip()
        allowed_intents = {"latest", "hot", "primary_sources", "deep_research", "source_trace", "compare", "explain", "general_search"}
        if intent not in allowed_intents:
            intent = fallback.intent
        days = max(1, min(int(data.get("timeframe_days", fallback.timeframe_days)), 90))
        keywords = [str(v).strip() for v in data.get("keywords", []) if str(v).strip()][:10] or fallback.keywords
        queries = [str(v).strip() for v in data.get("queries", []) if str(v).strip()][:6] or fallback.queries
        allowed_platforms = {"web", "arxiv", "github", "hacker_news", "x", "youtube"}
        platforms = [str(v) for v in data.get("platforms", []) if str(v) in allowed_platforms]
        if not platforms:
            platforms = fallback.platforms
        depth = max(1, min(int(data.get("depth", fallback.depth)), 3))
        return QueryPlan(
            original_query=text,
            topic=topic,
            intent=intent,
            timeframe_days=days,
            keywords=keywords,
            queries=queries,
            platforms=list(dict.fromkeys(platforms)),
            primary_only=bool(data.get("primary_only", fallback.primary_only)),
            depth=depth,
            rationale=str(data.get("rationale", "")).strip(),
        )
    except Exception as exc:
        print(f"[query-planner] LLM fallback: {exc}")
        return fallback
