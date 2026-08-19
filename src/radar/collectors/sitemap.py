from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from radar.models import CollectorResult, RadarItem
from radar.processing.normalize import clean_text

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SLUG_RE = re.compile(r"[-_/]+")


def _fetch_text(url: str, timeout: int = 15) -> str:
    request = Request(url, headers={"User-Agent": "research-engineer-radar/0.3"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _title_from_url(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    slug = path.split("/")[-1] if path else urlsplit(url).netloc
    return clean_text(SLUG_RE.sub(" ", slug)).title()


def parse_sitemap(xml_text: str, source_name: str, include_patterns: list[str] | None = None, limit: int = 12) -> list[RadarItem]:
    root = ET.fromstring(xml_text)
    include_patterns = include_patterns or []
    urls: list[tuple[str, datetime | None]] = []
    for node in root.findall("sm:url", SITEMAP_NS):
        loc = clean_text(node.findtext("sm:loc", default="", namespaces=SITEMAP_NS))
        if not loc:
            continue
        if include_patterns and not any(pattern in loc for pattern in include_patterns):
            continue
        lastmod = _parse_date(clean_text(node.findtext("sm:lastmod", default="", namespaces=SITEMAP_NS)))
        urls.append((loc, lastmod))
    urls.sort(key=lambda pair: pair[1] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    items = []
    for url, published in urls[:limit]:
        items.append(RadarItem(
            title=_title_from_url(url),
            url=url,
            source=source_name,
            summary=f"Official sitemap discovery from {source_name}.",
            published_at=published,
            tags=["sitemap", "official"],
            raw={"discovery": "sitemap"},
        ))
    return items


def collect_sitemaps(sources: list[dict], default_limit: int = 12) -> list[CollectorResult]:
    results: list[CollectorResult] = []
    for source in sources:
        name, url = source["name"], source["url"]
        start = time.perf_counter()
        try:
            limit = int(source.get("limit", default_limit))
            patterns = list(source.get("include_patterns", []))
            items = parse_sitemap(_fetch_text(url, int(source.get("timeout", 15))), name, patterns, limit)
            latency = time.perf_counter() - start
            results.append(CollectorResult(source=name, items=items, status="OK", latency_seconds=latency, details={"url": url}))
            print(f"[collector:sitemap] {name}: OK {len(items)} {latency:.2f}s")
        except Exception as exc:
            latency = time.perf_counter() - start
            results.append(CollectorResult(source=name, items=[], status="FAIL", latency_seconds=latency, error=str(exc), details={"url": url}))
            print(f"[collector:sitemap] {name}: FAIL {exc}")
    return results
