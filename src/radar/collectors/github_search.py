from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from radar.models import RadarItem


def collect_github(queries: list[str], per_query: int = 8) -> list[RadarItem]:
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "research-engineer-radar/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    results: list[RadarItem] = []
    for query in queries:
        params = urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": per_query})
        request = Request(f"https://api.github.com/search/repositories?{params}", headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            for repo in payload.get("items", []):
                pushed_at = repo.get("pushed_at")
                published = datetime.fromisoformat(pushed_at.replace("Z", "+00:00")) if pushed_at else None
                stars = repo.get("stargazers_count", 0)
                results.append(RadarItem(title=f"{repo.get('full_name')} ({stars}★)", url=repo.get("html_url", ""), source="GitHub Search", summary=repo.get("description") or "", published_at=published, tags=["github", repo.get("language") or ""], raw={"stars": stars, "query": query}))
        except Exception as exc:
            results.append(RadarItem(title=f"GitHub collector error: {query}", url="https://github.com/search", source="Radar System", summary=str(exc), tags=["collector-error"]))
    return results
