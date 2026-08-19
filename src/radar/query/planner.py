from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

from radar.ai.analyzer import _post_chat, extract_json_object


PLANNER_SYSTEM_PROMPT = """你是 Research Navigator V1.0 的 Query Planner。
用户会用自然语言描述想找的信息。你的任务不是回答问题，而是把自然语言转成可执行的研究计划。

不要机械提取关键词。先理解用户真正想解决的问题，再决定：
- topic：归一化主题
- intent：latest / hot / primary_sources / deep_research / source_trace / compare / explain / general_search
- timeframe_days：时间窗口
- keywords：用于相关性判断的核心概念
- queries：真正发送给搜索引擎/论文库/代码库的子查询
- platforms：web / arxiv / github / hacker_news / x / youtube
- primary_only：是否优先原始来源
- depth：沿链接/引用继续探索的深度
- must_include：结果最好必须出现的概念
- exclude_terms：用户明确不要的内容
- rationale：为什么这样拆解

规则：
1. “今天/24小时”=1天；“最近一周”=7天；“最近一个月”=30天；“最近/最新/热点”默认7天；无时间要求默认30天。
2. 用户强调源头、一手、官方、作者原帖、原论文、原仓库时 primary_only=true。
3. 用户说深挖、追溯、来源链、顺着链接/引用继续找，depth=2或3；普通搜索 depth=1。
4. 用户说“不要浅教程/不要营销/只要论文”等要求必须落到 exclude_terms / must_include / platforms，而不是丢失。
5. 子查询最多6个，优先补充英文专业术语、同义词、机制词、failure/evaluation/benchmark 等有区分度的词，不要堆泛词。
6. 除非用户明确限定平台，否则默认覆盖 web/arxiv/github/hacker_news/x/youtube；后端会根据可用凭据自动降级。
7. 只返回 JSON，不要 Markdown。"""


@dataclass(slots=True)
class QueryPlan:
    original_query: str
    topic: str
    intent: str = "general_search"
    timeframe_days: int = 30
    keywords: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: ["web", "arxiv", "github", "hacker_news", "x", "youtube"])
    primary_only: bool = False
    depth: int = 1
    must_include: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_exclusions(text: str) -> list[str]:
    found: list[str] = []
    patterns = [
        r"不要\s*([^，。；;！!\n]{2,24})",
        r"排除\s*([^，。；;！!\n]{2,24})",
        r"别给我\s*([^，。；;！!\n]{2,24})",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            value = re.sub(r"\s+", " ", match).strip()
            if value:
                found.append(value)
    return list(dict.fromkeys(found))[:6]


def _fallback_plan(text: str) -> QueryPlan:
    lowered = text.lower()
    days = 30
    if any(token in text for token in ["今天", "今日", "24小时", "24 小时", "过去一天"]):
        days = 1
    elif any(token in text for token in ["最近一周", "近一周", "7天", "7 天", "过去一周"]):
        days = 7
    elif any(token in text for token in ["最近一个月", "近一个月", "30天", "30 天"]):
        days = 30
    elif any(token in text for token in ["最近", "最新", "热点", "热门", "前沿"]):
        days = 7

    intent = "general_search"
    if any(token in text for token in ["源头", "来源链", "追溯", "原始来源", "作者原帖"]):
        intent = "source_trace"
    elif any(token in text for token in ["深挖", "深入", "继续找", "顺着", "往下找"]):
        intent = "deep_research"
    elif any(token in text for token in ["对比", "比较", "区别"]):
        intent = "compare"
    elif any(token in text for token in ["解释", "为什么"]):
        intent = "explain"
    elif any(token in text for token in ["热点", "热门", "为什么突然", "变热"]):
        intent = "hot"
    elif any(token in text for token in ["最新", "最近"]):
        intent = "latest"

    primary_only = any(token in text for token in ["一手", "官方", "源头", "原始来源", "作者原帖", "原论文", "原仓库"])
    if primary_only and intent == "general_search":
        intent = "primary_sources"

    depth = 3 if intent == "source_trace" else 2 if intent == "deep_research" else 1
    stop = {"最近", "最新", "热点", "热门", "帮我", "找一下", "看看", "什么", "有没有", "值得看的", "一手来源"}
    words = [
        w.strip()
        for w in re.split(r"[\s,，。！？;；:：()（）【】]+", text)
        if len(w.strip()) > 1 and w.strip() not in stop
    ]
    keywords = words[:10]

    platforms = ["web", "arxiv", "github", "hacker_news", "x", "youtube"]
    explicit: list[str] = []
    platform_tokens = {
        "arxiv": ["论文", "paper", "arxiv"],
        "github": ["github", "代码", "仓库", "repo"],
        "hacker_news": ["hacker news", "hn"],
        "x": ["twitter", "x.com", "推特", "x 上", "x上", "作者原帖"],
        "youtube": ["youtube", "油管", "视频", "演讲"],
        "web": ["官网", "博客", "网站", "web"],
    }
    for platform, tokens in platform_tokens.items():
        if any(token in lowered for token in tokens):
            explicit.append(platform)
    if explicit and any(token in text for token in ["只看", "只要", "仅看", "仅要"]):
        platforms = explicit

    must_include: list[str] = []
    if "只看一手" in text or "只要一手" in text:
        primary_only = True
    if "只看论文" in text or "只要论文" in text:
        platforms = ["arxiv"]
        must_include.append("paper")
    if "只看代码" in text or "只要代码" in text or "只看GitHub" in text:
        platforms = ["github"]
        must_include.append("code")

    exclude_terms = _extract_exclusions(text)
    return QueryPlan(
        original_query=text,
        topic=text.strip()[:140],
        intent=intent,
        timeframe_days=days,
        keywords=keywords,
        queries=[text.strip()],
        platforms=list(dict.fromkeys(platforms)),
        primary_only=primary_only,
        depth=depth,
        must_include=must_include,
        exclude_terms=exclude_terms,
        rationale="deterministic_fallback",
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
        "recent_conversation": (history or [])[-8:],
        "radar_focus": config.get("radar_focus", {}),
        "required_output": {
            "topic": "一句话归一化主题，保留技术实体名",
            "intent": "latest/hot/primary_sources/deep_research/source_trace/compare/explain/general_search",
            "timeframe_days": "1-90整数",
            "keywords": "核心概念数组，最多10个",
            "queries": "搜索子查询数组，最多6个，优先英文专业术语+必要中文",
            "platforms": "web/arxiv/github/hacker_news/x/youtube 的子集",
            "primary_only": "boolean",
            "depth": "1-3整数",
            "must_include": "必须满足的内容要求数组，最多6个",
            "exclude_terms": "用户明确不要的内容数组，最多6个",
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
        allowed_intents = {"latest", "hot", "primary_sources", "deep_research", "source_trace", "compare", "explain", "general_search"}
        allowed_platforms = {"web", "arxiv", "github", "hacker_news", "x", "youtube"}

        topic = str(data.get("topic") or fallback.topic).strip()[:180]
        intent = str(data.get("intent") or fallback.intent).strip()
        if intent not in allowed_intents:
            intent = fallback.intent
        days = max(1, min(int(data.get("timeframe_days", fallback.timeframe_days)), 90))
        keywords = [str(v).strip() for v in data.get("keywords", []) if str(v).strip()][:10] or fallback.keywords
        queries = [str(v).strip() for v in data.get("queries", []) if str(v).strip()][:6] or fallback.queries
        platforms = [str(v) for v in data.get("platforms", []) if str(v) in allowed_platforms] or fallback.platforms
        depth = max(1, min(int(data.get("depth", fallback.depth)), 3))
        must_include = [str(v).strip() for v in data.get("must_include", []) if str(v).strip()][:6] or fallback.must_include
        exclude_terms = [str(v).strip() for v in data.get("exclude_terms", []) if str(v).strip()][:6]
        if not exclude_terms:
            exclude_terms = fallback.exclude_terms
        primary_only = bool(data.get("primary_only", fallback.primary_only))
        if intent in {"primary_sources", "source_trace"}:
            primary_only = True

        return QueryPlan(
            original_query=text,
            topic=topic,
            intent=intent,
            timeframe_days=days,
            keywords=keywords,
            queries=queries,
            platforms=list(dict.fromkeys(platforms)),
            primary_only=primary_only,
            depth=depth,
            must_include=must_include,
            exclude_terms=exclude_terms,
            rationale=str(data.get("rationale", "")).strip(),
        )
    except Exception as exc:
        print(f"[query-planner] LLM fallback: {exc}")
        return fallback
