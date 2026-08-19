from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from radar.models import RadarItem

SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "spm",
    "igshid",
}
TITLE_JUNK_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def canonical_url(url: str) -> str:
    if not url:
        return ""
    split = urlsplit(url.strip())
    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=False):
        low = key.lower()
        if low in TRACKING_KEYS or low.startswith("utm_"):
            continue
        query.append((key, value))
    path = split.path.rstrip("/") or split.path
    return urlunsplit((split.scheme.lower(), split.netloc.lower(), path, urlencode(query), ""))


def title_fingerprint(title: str) -> str:
    text = clean_text(title).lower()
    text = TITLE_JUNK_RE.sub(" ", text)
    stop = {"the", "a", "an", "and", "or", "of", "to", "for", "with", "in", "on", "is"}
    tokens = [token for token in text.split() if token not in stop]
    return " ".join(tokens[:18])


def item_id(title: str, url: str) -> str:
    base = canonical_url(url) or title_fingerprint(title)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def deduplicate_items(items: list[RadarItem]) -> list[RadarItem]:
    """Cross-source in-batch deduplication.

    URL is the primary key. Title fingerprint is a fallback for sources that expose
    different canonical URLs for the same paper/article. Collector failures are not
    normal content and are deliberately excluded here.
    """
    by_key: dict[str, RadarItem] = {}
    title_to_key: dict[str, str] = {}
    for item in items:
        if "collector-error" in item.tags:
            continue
        url_key = canonical_url(item.url)
        title_key = title_fingerprint(item.title)
        key = url_key or title_key
        if not key:
            continue
        existing_key = title_to_key.get(title_key, key) if title_key else key
        existing = by_key.get(existing_key)
        if existing is None:
            item.url = canonical_url(item.url) or item.url
            by_key[existing_key] = item
            if title_key:
                title_to_key[title_key] = existing_key
            continue
        if len(item.summary or "") > len(existing.summary or ""):
            existing.summary = item.summary
        if item.published_at and (existing.published_at is None or item.published_at > existing.published_at):
            existing.published_at = item.published_at
        existing.tags = sorted(set(existing.tags) | set(item.tags))
        sources = set(existing.raw.get("merged_sources", [existing.source]))
        sources.add(item.source)
        existing.raw["merged_sources"] = sorted(sources)
    return list(by_key.values())
