from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SPACE_RE = re.compile(r"\s+")
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return SPACE_RE.sub(" ", value).strip()


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
    return urlunsplit((split.scheme.lower(), split.netloc.lower(), split.path.rstrip("/"), urlencode(query), ""))


def item_id(title: str, url: str) -> str:
    base = canonical_url(url) or clean_text(title).lower()
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
