from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from radar.models import CollectorResult, RadarItem


def _get_json(url: str, timeout: int = 10):
    request = Request(url, headers={"User-Agent": "research-engineer-radar/0.3"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_hacker_news(config: dict | None = None) -> list[CollectorResult]:
    """Fetch AI/engineering HN stories via Algolia with a few focused queries."""
    cfg = config or {}
    limit = int(cfg.get("limit", 8))
    per_query = int(cfg.get("per_query", 4))
    lookback_days = int(cfg.get("lookback_days", 7))
    queries = list(cfg.get("queries", ["AI", "LLM", "inference", "machine learning"]))
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp())
    start = time.perf_counter()
    seen: set[str] = set()
    items: list[RadarItem] = []
    try:
        for query in queries:
            if len(items) >= limit:
                break
            params = urlencode({
                "query": str(query),
                "tags": "story",
                "hitsPerPage": per_query,
                "numericFilters": f"created_at_i>{since_ts}",
            })
            payload = _get_json(f"https://hn.algolia.com/api/v1/search_by_date?{params}", timeout=int(cfg.get("timeout", 12)))
            for hit in payload.get("hits", []):
                if len(items) >= limit:
                    break
                object_id = str(hit.get("objectID", ""))
                if object_id in seen:
                    continue
                seen.add(object_id)
                title = hit.get("title") or hit.get("story_title") or ""
                if not title:
                    continue
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
                published = datetime.fromtimestamp(int(hit.get("created_at_i", 0)), tz=timezone.utc) if hit.get("created_at_i") else None
                points = int(hit.get("points", 0) or 0)
                comments = int(hit.get("num_comments", 0) or 0)
                items.append(RadarItem(
                    title=title,
                    url=url,
                    source="Hacker News",
                    summary=f"HN discussion: {points} points, {comments} comments. Matched query: {query}.",
                    published_at=published,
                    tags=["community", "hacker-news", str(query).lower()],
                    raw={"hn_id": object_id, "hn_score": points, "hn_comments": comments, "query": query},
                ))
        latency = time.perf_counter() - start
        print(f"[collector:hn] Hacker News: OK {len(items)} {latency:.2f}s")
        return [CollectorResult(source="Hacker News", items=items, status="OK", latency_seconds=latency, details={"queries": queries})]
    except Exception as exc:
        latency = time.perf_counter() - start
        print(f"[collector:hn] Hacker News: FAIL {exc}")
        return [CollectorResult(source="Hacker News", items=[], status="FAIL", latency_seconds=latency, error=str(exc), details={"queries": queries})]
