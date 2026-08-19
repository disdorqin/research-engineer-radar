from __future__ import annotations

import json
import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from radar.models import CollectorResult, RadarItem
from radar.processing.normalize import clean_text


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect_huggingface_papers(config: dict | None = None) -> list[CollectorResult]:
    cfg = config or {}
    limit = int(cfg.get("limit", 10))
    params = urlencode({"limit": limit})
    url = f"https://huggingface.co/api/daily_papers?{params}"
    start = time.perf_counter()
    try:
        request = Request(url, headers={"User-Agent": "research-engineer-radar/0.3"})
        with urlopen(request, timeout=int(cfg.get("timeout", 15))) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items: list[RadarItem] = []
        for row in payload[:limit]:
            paper = row.get("paper", row)
            title = clean_text(paper.get("title") or row.get("title") or "")
            paper_id = paper.get("id") or ""
            link = f"https://huggingface.co/papers/{paper_id}" if paper_id else paper.get("projectPage") or "https://huggingface.co/papers"
            summary = clean_text(paper.get("ai_summary") or paper.get("summary") or row.get("summary") or "")
            published = _parse_date(row.get("publishedAt") or paper.get("submittedOnDailyAt") or paper.get("publishedAt"))
            keywords = paper.get("ai_keywords") or []
            if title:
                items.append(RadarItem(
                    title=title,
                    url=link,
                    source="HuggingFace Papers",
                    summary=summary,
                    published_at=published,
                    tags=["paper", "huggingface", *[str(keyword) for keyword in keywords[:8]]],
                    raw={
                        "paper_id": paper_id,
                        "upvotes": paper.get("upvotes", 0),
                        "githubRepo": paper.get("githubRepo", ""),
                        "projectPage": paper.get("projectPage", ""),
                    },
                ))
        latency = time.perf_counter() - start
        print(f"[collector:huggingface] HuggingFace Papers: OK {len(items)} {latency:.2f}s")
        return [CollectorResult(source="HuggingFace Papers", items=items, status="OK", latency_seconds=latency, details={"url": url})]
    except Exception as exc:
        latency = time.perf_counter() - start
        print(f"[collector:huggingface] HuggingFace Papers: FAIL {exc}")
        return [CollectorResult(source="HuggingFace Papers", items=[], status="FAIL", latency_seconds=latency, error=str(exc), details={"url": url})]
