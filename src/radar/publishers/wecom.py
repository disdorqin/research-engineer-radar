from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def publish_wecom(text: str) -> None:
    webhook = os.getenv("WECOM_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("WECOM_WEBHOOK_URL is missing")
    payload = {"msgtype": "markdown", "markdown": {"content": text[:4000]}}
    request = Request(webhook, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("errcode") not in (0, None):
        raise RuntimeError(f"WeCom send failed: {body}")
