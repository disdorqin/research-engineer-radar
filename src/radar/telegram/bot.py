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
from radar.research.search import ResearchResult, SourceNode, research


START_TEXT = """🔎 Research Navigator 已上线。

你不需要记命令，直接说人话就行，例如：
• 最近 Agent evaluation 有什么值得看的？
• 找最近一周 OpenAI / Anthropic 关于 Agent 设计的一手来源。
• Agent Skills 为什么最近突然变热？顺着来源继续往下找。
• 找 GPU utilization 的工程文章，不要浅教程。
• 深挖第 2 条。

我会先把你的自然语言拆成 topic、检索意图、时间范围、关键词和平台，再做多源检索，并尽量沿链接追溯到论文、官方博客、GitHub、X 或 YouTube。"""


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _request_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    if payload is None:
        request = Request(url, headers={"User-Agent": "research-navigator/0.5"})
    else:
        request = Request(
            url,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "research-navigator/0.5"},
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


def _badge(node: SourceNode) -> str:
    return {
        "paper": "📄",
        "code": "💻",
        "x": "𝕏",
        "video": "▶️",
        "discussion": "💬",
        "web": "🌐",
    }.get(node.kind, "🌐")


def _source_quality(node: SourceNode) -> str:
    if node.primary_score >= 0.88:
        return "一手/高可信"
    if node.primary_score >= 0.65:
        return "较强来源"
    return "延伸来源"


def _chain(node: SourceNode, result: ResearchResult) -> str:
    if not node.discovered_from:
        return ""
    by_url = {row.url: row for row in result.nodes}
    names = [node.title[:42]]
    cursor = node.discovered_from
    seen: set[str] = set()
    while cursor and cursor not in seen and len(names) < 4:
        seen.add(cursor)
        parent = by_url.get(cursor)
        if not parent:
            names.append(cursor)
            break
        names.append(parent.title[:42])
        cursor = parent.discovered_from
    names.reverse()
    return " → ".join(names)


def _short(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def render_search_result(result: ResearchResult, max_items: int = 6) -> str:
    plan = result.plan
    lines = [
        f"🔎 {plan.topic}",
        f"检索理解：{plan.intent} · 最近 {plan.timeframe_days} 天 · 深度 {plan.depth}",
        "",
    ]
    visible = result.nodes[:max_items]
    if not visible:
        lines.append("这次没有找到足够可靠的结果。你可以换一种说法，或扩大时间范围。")
        return "\n".join(lines)

    for idx, node in enumerate(visible, start=1):
        lines.append(f"{idx}. {_badge(node)} {node.title}")
        lines.append(f"{node.source} · {_source_quality(node)}")
        if node.summary:
            lines.append(_short(node.summary, 220))
        chain = _chain(node, result)
        if chain:
            lines.append(f"🔗 来源链：{_short(chain, 240)}")
        lines.append(node.url)
        lines.append("")

    if result.edges:
        lines.append(f"🌳 本轮已建立 {len(result.edges)} 条来源关系；可以继续说“深挖第2条”或“把第3条追到源头”。")
    else:
        lines.append("你可以继续说：深挖第2条 / 只看一手来源 / 找作者的 X 和 YouTube / 换成最近24小时。")
    if result.warnings:
        lines.append(f"部分来源暂不可用：{', '.join(result.warnings[:2])}")
    return "\n".join(lines).strip()


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
        state = chats.setdefault(chat_id, {"history": [], "last_results": [], "last_topic": "", "last_query": ""})
        state.setdefault("history", [])
        state.setdefault("last_results", [])
        return state

    def send_typing(self, chat_id: str) -> None:
        try:
            _request_json(_api_url(self.token, "sendChatAction"), {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception:
            pass

    def send_message(self, chat_id: str, text: str) -> None:
        for chunk in _chunks(text):
            payload = _request_json(
                _api_url(self.token, "sendMessage"),
                {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"},
                timeout=20,
            )
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram sendMessage failed: {payload}")

    def _history_for_planner(self, chat: dict) -> list[dict]:
        history = list(chat.get("history", []))[-6:]
        if chat.get("last_topic"):
            history.append({"role": "assistant", "content": f"上一轮研究主题：{chat['last_topic']}"})
        return history[-7:]

    def answer(self, chat_id: str, text: str) -> str:
        chat = self._chat_state(chat_id)
        clean = text.strip()
        if clean in {"/start", "/help", "start", "帮助", "怎么用"}:
            return START_TEXT

        effective_text = clean
        if chat.get("last_topic") and any(token in clean for token in ["继续", "深挖", "只看", "源头", "一手", "作者", "X", "YouTube", "油管", "第"]):
            effective_text = f"围绕上一轮主题“{chat['last_topic']}”，用户继续要求：{clean}"

        history = self._history_for_planner(chat)
        plan = plan_query(effective_text, self.config, history=history)
        seed_url: str | None = None
        index = _ordinal(clean)
        if index is not None and index <= len(chat.get("last_results", [])):
            seed_url = chat["last_results"][index - 1].get("url")
            plan.depth = max(plan.depth, 2)
            if plan.intent == "general_search":
                plan.intent = "deep_research"

        result = research(plan, self.config, seed_url=seed_url)
        visible = result.nodes[:8]
        chat["last_results"] = [
            {"title": node.title, "url": node.url, "source": node.source, "kind": node.kind}
            for node in visible
        ]
        chat["last_topic"] = plan.topic
        chat["last_query"] = clean
        chat["history"] = (chat.get("history", []) + [{"role": "user", "content": clean}])[-8:]
        self.save_state()
        return render_search_result(result, max_items=int(self.config.get("interactive_search", {}).get("telegram_max_items", 6)))

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
            reply = f"这次检索失败了：{type(exc).__name__}: {exc}\n\n你可以稍后重试，或者先缩小搜索范围。"
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
        print(f"[telegram] Research Navigator live for up to {seconds}s")
        while time.monotonic() < deadline:
            try:
                self.poll_once(timeout_seconds=min(20, max(1, int(deadline - time.monotonic()))))
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
