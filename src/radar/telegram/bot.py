from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from radar.config import load_config
from radar.query.planner import QueryPlan, plan_query
from radar.research.provenance import relation_label
from radar.research.search import ResearchResult, SourceNode, research


START_TEXT = """🔎 Research Navigator V1.0

直接说人话，不需要记命令。你可以这样问：
• 最近 Agent evaluation 有什么真正值得看的？优先一手来源。
• Agent Skills 为什么突然变热？帮我找源头，再顺着论文、代码和作者讨论往下找。
• 找 GPU utilization 的工程文章，不要浅教程。
• 最近一周 OpenAI / Anthropic 在 Agent 设计上有什么新东西？
• 最近最火的 AI 工程新闻是什么？
• 深挖第 2 条。
• 把第 3 条追到源头。
• 只看论文和代码。
• 扩大范围重新搜。
• 这个链接继续往下挖：https://...

我会先把自然语言拆成 Topic / Intent / 时间范围 / 关键词 / 子查询 / 平台 / 一手来源偏好，再进行多源检索和来源链探索。"""

_GREETING_RE = re.compile(r"^\s*(/start|/help|start|help|hello|hi|hey|你好|您好|嗨|哈喽|帮助|怎么用)[!！。.？?\s]*$", re.I)


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _request_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    if payload is None:
        request = Request(url, headers={"User-Agent": "research-navigator/1.0"})
    else:
        request = Request(
            url,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "research-navigator/1.0"},
            method="POST",
        )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _chunks(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _ordinal(text: str) -> int | None:
    match = re.search(r"第?\s*([0-9]{1,2}|[一二三四五六七八九十])\s*条", text)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        value = int(raw)
        return value if value > 0 else None
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return mapping.get(raw)


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>\]）)]+", text)
    return match.group(0).rstrip("，。！？；;") if match else None


def _badge(node: SourceNode) -> str:
    return {"paper": "📄", "code": "💻", "x": "𝕏", "video": "▶️", "discussion": "💬", "web": "🌐"}.get(node.kind, "🌐")


def _source_quality(node: SourceNode) -> str:
    if node.primary_score >= 0.90:
        return "一手/官方"
    if node.primary_score >= 0.75:
        return "高可信"
    if node.primary_score >= 0.55:
        return "较强来源"
    return "延伸讨论"


def _short(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _intent_label(intent: str) -> str:
    return {"latest": "最新", "hot": "热点", "primary_sources": "一手来源", "deep_research": "深挖", "source_trace": "追溯源头", "compare": "对比", "explain": "解释", "general_search": "综合检索"}.get(intent, intent)


def _chain(node: SourceNode, result: ResearchResult) -> str:
    if not node.discovered_from:
        return ""
    by_url = {row.url: row for row in result.nodes}
    parts = [node.title[:36]]
    relations = [relation_label(node.relation)]
    cursor = node.discovered_from
    seen: set[str] = set()
    while cursor and cursor not in seen and len(parts) < 4:
        seen.add(cursor)
        parent = by_url.get(cursor)
        if not parent:
            parts.append(cursor[:36])
            break
        parts.append(parent.title[:36])
        if parent.discovered_from:
            relations.append(relation_label(parent.relation))
        cursor = parent.discovered_from
    parts.reverse()
    relations.reverse()
    if len(parts) <= 1:
        return ""
    chain = parts[0]
    for idx, name in enumerate(parts[1:]):
        rel = relations[idx] if idx < len(relations) else "链接到"
        chain += f" —{rel}→ {name}"
    return chain


def render_search_result(result: ResearchResult, max_items: int = 6, note: str = "") -> str:
    plan = result.plan
    lines = [f"🔎 {plan.topic}", f"{_intent_label(plan.intent)} · 最近 {plan.timeframe_days} 天" + (" · 优先一手" if plan.primary_only else "") + (f" · 深度 {plan.depth}" if plan.depth > 1 else ""), ""]
    if note:
        lines.append(note)
        lines.append("")
    visible = result.nodes[:max_items]
    if not visible:
        if result.trace:
            providers = result.trace.provider_counts or {}
            provider_text = " · ".join(f"{k}={v}" for k, v in providers.items()) or "none"
            lines.append(f"这次仍然没有找到足够可靠的结果。已尝试来源：{provider_text}。")
        else:
            lines.append("这次仍然没有找到足够可靠的结果。")
        lines.append("你可以直接换成更具体的问题，例如：最近 Agent Skills 的论文和代码 / 最近 OpenAI Anthropic Agent 工程更新 / 最近最火 AI agent 新闻。")
        return "\n".join(lines)
    for idx, node in enumerate(visible, start=1):
        lines.append(f"{idx}. {_badge(node)} {node.title}")
        lines.append(f"{node.source} · {_source_quality(node)}")
        if node.summary:
            lines.append(_short(node.summary, 210))
        chain = _chain(node, result)
        if chain:
            lines.append(f"🔗 {_short(chain, 260)}")
        lines.append(node.url)
        lines.append("")
    if result.edges:
        lines.append("🌳 已建立来源关系。可以直接说“深挖第2条”“把第3条追到源头”或“找作者的 X / YouTube”。")
    else:
        lines.append("继续说：深挖第2条 / 只看一手来源 / 只看论文和代码 / 换成最近24小时。")
    return "\n".join(lines).strip()


def _provider_status(config: dict) -> str:
    cfg = config.get("interactive_search", {})
    x_env = cfg.get("x_bearer_token_env", "X_BEARER_TOKEN")
    yt_env = cfg.get("youtube_api_key_env", "YOUTUBE_API_KEY")
    searx_env = cfg.get("searxng_base_url_env", "SEARXNG_BASE_URL")
    lines = ["🧭 Research Navigator V1.0 状态", "", "基础来源：Web / arXiv / GitHub / Hacker News ✅", f"X 官方搜索：{'✅' if os.getenv(x_env) else '↪ Web fallback'}", f"YouTube 官方搜索：{'✅' if os.getenv(yt_env) else '↪ Web fallback'}", f"SearXNG：{'✅' if os.getenv(searx_env) else '↪ DuckDuckGo fallback'}", "来源图：Best-first traversal ✅", "Provenance：引用/代码/讨论/演讲关系识别 ✅", "Observability：每轮 trace ✅"]
    return "\n".join(lines)


def _trace_text(chat: dict) -> str:
    trace = chat.get("last_trace") or {}
    if not trace:
        return "还没有可查看的检索 Trace。先问一个问题。"
    providers = trace.get("provider_counts") or {}
    provider_text = " · ".join(f"{k}={v}" for k, v in providers.items()) or "none"
    return f"🧪 Trace {trace.get('trace_id', '-')}\n耗时：{trace.get('duration_ms', 0)} ms\n节点：{trace.get('nodes', 0)} · 关系：{trace.get('edges', 0)} · 深挖页面：{trace.get('crawl_fetches', 0)}\n来源：{provider_text}\nwarnings：{len(trace.get('warnings') or [])}"


def _needs_broaden(text: str) -> bool:
    return any(token in text for token in ["扩大", "放宽", "上调", "换一个", "换成", "最火", "热点", "热门", "新闻", "前沿"])


def _make_broadened_plan(plan: QueryPlan, clean: str) -> QueryPlan:
    topic = plan.topic
    lowered = clean.lower()
    agentish = any(token in lowered for token in ["agent", "skills", "智能体", "代理"])
    if any(token in clean for token in ["最火", "热点", "热门", "新闻", "前沿"]):
        topic = "AI Agent / LLM 工程热点与一手动态"
    elif agentish:
        topic = "AI Agent / Agent Skills 最新一手来源与工程讨论"

    if agentish:
        queries = [
            "agent skills agent evaluation source code paper",
            "AI agent skills reliability evaluation GitHub arXiv",
            "OpenAI Anthropic agent skills tool use memory evaluation",
            "site:x.com agent skills AI agents evaluation",
            "Hacker News AI agents agent skills evaluation",
        ]
        keywords = ["agent skills", "AI agents", "agent evaluation", "tool use", "memory", "reliability", "OpenAI", "Anthropic"]
    else:
        queries = [
            "AI agents OpenAI Anthropic latest research engineering",
            "LLM agents evaluation reliability tool use latest",
            "AI engineering LLM serving agents Hacker News GitHub",
            "site:x.com AI agents OpenAI Anthropic latest",
            "latest AI research engineering agent infrastructure",
        ]
        keywords = ["AI agents", "LLM agents", "OpenAI", "Anthropic", "AI engineering", "LLM serving", "evaluation", "infrastructure"]

    return QueryPlan(
        original_query=plan.original_query,
        topic=topic,
        intent="hot" if any(token in clean for token in ["最火", "热点", "热门", "新闻", "前沿"]) else "deep_research",
        timeframe_days=max(7, min(max(plan.timeframe_days, 30), 90)),
        keywords=keywords,
        queries=queries,
        platforms=["web", "arxiv", "github", "hacker_news", "x", "youtube"],
        primary_only=False,
        depth=max(2, plan.depth),
        must_include=[] if any(token in clean for token in ["最火", "热点", "热门", "新闻", "前沿"]) else plan.must_include,
        exclude_terms=list(dict.fromkeys([*plan.exclude_terms, "beginner tutorial", "quickstart", "浅教程", "营销"])),
        rationale="auto_broaden_after_empty_result",
    )


class TelegramResearchBot:
    def __init__(self, config_path: str = "config/radar.json") -> None:
        cfg = load_config(config_path)
        self.config = cfg.data
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
        interactive_cfg = self.config.get("interactive_search", {})
        self.state_path = Path(interactive_cfg.get("session_state_path", "data/telegram_sessions.json"))
        self.state = self._load_state()
        self.offset = int(self.state.get("update_offset", 0))

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"update_offset": 0, "chats": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            payload.setdefault("update_offset", 0)
            payload.setdefault("chats", {})
            return payload
        except Exception:
            return {"update_offset": 0, "chats": {}}

    def save_state(self) -> None:
        self.state["update_offset"] = self.offset
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _chat_state(self, chat_id: str) -> dict:
        chats = self.state.setdefault("chats", {})
        state = chats.setdefault(chat_id, {"history": [], "last_results": [], "last_topic": "", "last_query": "", "last_trace": {}})
        state.setdefault("history", [])
        state.setdefault("last_results", [])
        state.setdefault("last_trace", {})
        return state

    def send_typing(self, chat_id: str) -> None:
        try:
            _request_json(_api_url(self.token, "sendChatAction"), {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception:
            pass

    def send_message(self, chat_id: str, text: str) -> None:
        for chunk in _chunks(text):
            payload = _request_json(_api_url(self.token, "sendMessage"), {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"}, timeout=20)
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram sendMessage failed: {payload}")

    def _history_for_planner(self, chat: dict) -> list[dict]:
        history = list(chat.get("history", []))[-8:]
        if chat.get("last_topic"):
            history.append({"role": "assistant", "content": f"上一轮研究主题：{chat['last_topic']}"})
        return history[-9:]

    def answer(self, chat_id: str, text: str) -> str:
        chat = self._chat_state(chat_id)
        clean = text.strip()
        lowered = clean.lower()
        if _GREETING_RE.match(clean):
            return START_TEXT
        if lowered in {"/status", "status", "状态"}:
            return _provider_status(self.config)
        if lowered in {"/trace", "trace", "调试", "本轮状态"}:
            return _trace_text(chat)

        effective_text = clean
        continuation_tokens = ["继续", "深挖", "只看", "只要", "源头", "一手", "作者", "youtube", "油管", "第", "换成", "换一个", "追到", "扩大", "放宽", "上调"]
        if chat.get("last_topic") and any(token in lowered for token in continuation_tokens):
            effective_text = f"围绕上一轮主题“{chat['last_topic']}”，用户继续要求：{clean}"
        history = self._history_for_planner(chat)
        plan = plan_query(effective_text, self.config, history=history)

        seed_url = _first_url(clean)
        index = _ordinal(clean)
        if index is not None:
            last_results = chat.get("last_results", [])
            if index > len(last_results):
                if not last_results and chat.get("last_query"):
                    effective_text = f"上一轮没有可深挖条目。请扩大范围重新检索上一轮问题：{chat['last_query']}。用户继续要求：{clean}"
                    plan = plan_query(effective_text, self.config, history=history)
                    seed_url = None
                else:
                    return f"上一轮只有 {len(last_results)} 条可继续探索的结果，没有第 {index} 条。你可以说“扩大范围重新搜”。"
            else:
                seed_url = last_results[index - 1].get("url")
                plan.depth = max(plan.depth, 2)
                if plan.intent in {"general_search", "latest", "hot"}:
                    plan.intent = "deep_research"
        elif seed_url:
            plan.depth = max(plan.depth, 2)
            if plan.intent == "general_search":
                plan.intent = "deep_research"

        result = research(plan, self.config, seed_url=seed_url)
        note = ""
        if not result.nodes and seed_url is None:
            broadened = _make_broadened_plan(plan, clean if not chat.get("last_query") else f"{clean} {chat.get('last_query')}")
            result = research(broadened, self.config, seed_url=None)
            plan = broadened
            note = "第一次检索没有可用结果，我已经自动放宽关键词、扩大时间范围，并取消过强的一手来源限制。"
        elif _needs_broaden(clean) and seed_url is None and len(result.nodes) < 3:
            broadened = _make_broadened_plan(plan, clean)
            broadened.depth = max(broadened.depth, 2)
            second = research(broadened, self.config, seed_url=None)
            if len(second.nodes) > len(result.nodes):
                result = second
                plan = broadened
                note = "我按你的意思把检索范围上调了：关键词更宽、平台更多、时间窗口更大。"

        visible = result.nodes[:10]
        chat["last_results"] = [{"title": node.title, "url": node.url, "source": node.source, "kind": node.kind} for node in visible]
        chat["last_topic"] = plan.topic
        chat["last_query"] = clean
        chat["last_trace"] = result.trace.to_dict() if result.trace else {}
        chat["history"] = (chat.get("history", []) + [{"role": "user", "content": clean}, {"role": "assistant", "content": f"已检索主题：{plan.topic}，结果数：{len(visible)}"}])[-10:]
        self.save_state()
        return render_search_result(result, max_items=int(self.config.get("interactive_search", {}).get("telegram_max_items", 6)), note=note)

    def process_update(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        text = message.get("text")
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        if not text or not chat_id:
            return
        allowed_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if allowed_chat and chat_id != allowed_chat:
            self.send_message(chat_id, "这个 Research Navigator 当前只对已配置的私人 Chat ID 开放。")
            return
        self.send_typing(chat_id)
        try:
            reply = self.answer(chat_id, text)
        except Exception as exc:
            print(f"[telegram] query failed: {exc}")
            reply = f"这次检索失败了：{type(exc).__name__}: {exc}\n\n可以稍后重试，或先缩小搜索范围。"
        self.send_message(chat_id, reply)

    def get_updates(self, timeout_seconds: int = 20) -> list[dict]:
        query = urlencode({"timeout": timeout_seconds, "offset": self.offset, "allowed_updates": json.dumps(["message", "edited_message"])})
        payload = _request_json(_api_url(self.token, "getUpdates") + "?" + query, timeout=timeout_seconds + 8)
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {payload}")
        return payload.get("result", [])

    def poll_once(self, timeout_seconds: int = 2) -> int:
        updates = self.get_updates(timeout_seconds=timeout_seconds)
        for update in updates:
            update_id = int(update.get("update_id", 0))
            self.process_update(update)
            self.offset = max(self.offset, update_id + 1)
            self.save_state()
        return len(updates)

    def serve(self, seconds: int = 1620) -> None:
        deadline = time.monotonic() + max(1, seconds)
        print(f"[telegram] Research Navigator V1.0 live for up to {seconds}s")
        while time.monotonic() < deadline:
            try:
                remaining = max(1, int(deadline - time.monotonic()))
                self.poll_once(timeout_seconds=min(20, remaining))
            except Exception as exc:
                print(f"[telegram] polling error: {exc}")
                time.sleep(3)
        self.save_state()
        print("[telegram] live window completed")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the interactive Telegram Research Navigator")
    parser.add_argument("--config", default="config/radar.json")
    parser.add_argument("--once", action="store_true", help="Poll Telegram once and exit")
    parser.add_argument("--serve-seconds", type=int, default=1620, help="Long-poll service window in seconds")
    parser.add_argument("--query", default="", help="Run one research query locally and print the Telegram-style result")
    args = parser.parse_args(argv)
    if args.query:
        cfg = load_config(args.config)
        plan = plan_query(args.query, cfg.data)
        print(render_search_result(research(plan, cfg.data)))
        return
    bot = TelegramResearchBot(args.config)
    if args.once:
        bot.poll_once(timeout_seconds=2)
    else:
        bot.serve(args.serve_seconds)


if __name__ == "__main__":
    main()
