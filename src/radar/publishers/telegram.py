from __future__ import annotations

import json
import os
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


def publish_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Telegram secrets are missing: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for idx, part in enumerate(split_message(text), start=1):
        suffix = f"\n\n({idx})" if len(text) > 3900 else ""
        payload = urlencode({"chat_id": chat_id, "text": part + suffix, "disable_web_page_preview": "true"}).encode("utf-8")
        request = Request(url, data=payload, method="POST")
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram send failed: {body}")
