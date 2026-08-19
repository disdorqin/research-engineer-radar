from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from radar.models import CollectorResult, RadarItem


def build_github_query(query: str, lookback_days: int = 30, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=lookback_days)).date().isoformat()
    if "{since}" in query:
        return query.replace("{since}", since)
    if "pushed:>" not in query and "pushed:" not in query:
        return f"{query} pushed:>{since}"
    return query


def _query_spec(spec: str | dict, default_lookback_days: int) -> tuple[str, int, int]:
    if isinstance(spec, str):
        return spec, default_lookback_days, 8
    return str(spec.get("query", "")), int(spec.get("lookback_days", default_lookback_days)), int(spec.get("limit", 8))


def collect_github(queries: list[str | dict], per_query: int = 8, default_lookback_days: int = 30) -> list[CollectorResult]:
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "research-engineer-radar/0.3"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    results: list[CollectorResult] = []
    for spec in queries:
        raw_query, lookback_days, limit = _query_spec(spec, default_lookback_days)
        if not raw_query:
            continue
        query = build_github_query(raw_query, lookback_days)
        start = time.perf_counter()
        params = urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": min(limit or per_query, 20)})
        request = Request(f"https://api.github.com/search/repositories?{params}", headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            batch = []
            for repo in payload.get("items", []):
                pushed_at = repo.get("pushed_at")
                created_at = repo.get("created_at")
                published = datetime.fromisoformat(pushed_at.replace("Z", "+00:00")) if pushed_at else None
                stars = repo.get("stargazers_count", 0)
                topics = repo.get("topics") or []
                batch.append(RadarItem(
                    title=f"{repo.get('full_name')} ({stars}★)",
                    url=repo.get("html_url", ""),
                    source="GitHub Search",
                    summary=repo.get("description") or "",
                    published_at=published,
                    tags=[tag for tag in ["github", repo.get("language") or "", *topics[:6]] if tag],
                    raw={
                        "stars": stars,
                        "query": query,
                        "raw_query": raw_query,
                        "forks": repo.get("forks_count", 0),
                        "open_issues": repo.get("open_issues_count", 0),
                        "created_at": created_at,
                        "pushed_at": pushed_at,
                        "language": repo.get("language") or "",
                        "topics": topics,
                    },
                ))
            latency = time.perf_counter() - start
            results.append(CollectorResult(source="GitHub Search", items=batch, status="OK", latency_seconds=latency, details={"query": query}))
            print(f"[collector:github] {query}: OK {len(batch)} {latency:.2f}s")
        except Exception as exc:
            latency = time.perf_counter() - start
            results.append(CollectorResult(source="GitHub Search", items=[], status="FAIL", latency_seconds=latency, error=str(exc), details={"query": query}))
            print(f"[collector:github] {query}: FAIL {exc}")
    return results
