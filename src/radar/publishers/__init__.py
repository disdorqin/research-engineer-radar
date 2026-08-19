from __future__ import annotations

from radar.publishers.telegram import publish_telegram


def publish_enabled(digest: str, config: dict) -> list[str]:
    sent: list[str] = []
    publishers = config.get("publishers", {})
    if publishers.get("telegram", {}).get("enabled", False):
        publish_telegram(digest)
        sent.append("telegram")
    return sent


__all__ = ["publish_enabled", "publish_telegram"]
