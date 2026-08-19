from __future__ import annotations

import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit and current:
            parts.append("".join(current))
            current = []
            current_len = 0
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current.append(line)
        current_len += len(line)
    if current:
        parts.append("".join(current))
    return parts


def compact_for_telegram(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    total = 0
    for line in lines:
        if line.startswith("排序信号："):
            continue
        total += len(line) + 1
        if total > max_chars:
            kept.append("\n……完整日报请看 reports/ 中的 Markdown artifact。")
            break
        kept.append(line)
    return "\n".join(kept)


def publish_telegram(text: str, retries: int = 2) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Telegram secrets are missing: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    message = compact_for_telegram(text)
    parts = split_message(message)
    for idx, part in enumerate(parts, start=1):
        suffix = f"\n\n({idx}/{len(parts)})" if len(parts) > 1 else ""
        payload = urlencode({"chat_id": chat_id, "text": part + suffix, "disable_web_page_preview": "true"}).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                request = Request(url, data=payload, method="POST")
                with urlopen(request, timeout=20) as response:
                    status = response.status
                    body = json.loads(response.read().decode("utf-8"))
                if status >= 400 or not body.get("ok"):
                    raise RuntimeError(f"Telegram send failed: status={status} body={body}")
                break
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    raise RuntimeError(f"Telegram send failed after retries: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))
        if last_error is None:
            continue
