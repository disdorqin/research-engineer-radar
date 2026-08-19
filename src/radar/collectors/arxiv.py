from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from radar.models import CollectorResult, RadarItem
from radar.processing.normalize import clean_text

NS = {"atom": "http://www.w3.org/2005/Atom"}


def collect_arxiv(queries: list[str | dict], per_query: int = 8) -> list[CollectorResult]:
    results: list[CollectorResult] = []
    for spec in queries:
        query = spec if isinstance(spec, str) else str(spec.get("query", ""))
        limit = per_query if isinstance(spec, str) else int(spec.get("limit", per_query))
        if not query:
            continue
        start = time.perf_counter()
        params = urlencode({"search_query": query, "start": 0, "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"})
        request = Request(f"https://export.arxiv.org/api/query?{params}", headers={"User-Agent": "research-engineer-radar/0.3"})
        try:
            with urlopen(request, timeout=20) as response:
                root = ET.fromstring(response.read())
            batch: list[RadarItem] = []
            for entry in root.findall("atom:entry", NS):
                title = clean_text(entry.findtext("atom:title", default="", namespaces=NS))
                summary = clean_text(entry.findtext("atom:summary", default="", namespaces=NS))
                url = entry.findtext("atom:id", default="", namespaces=NS)
                published_text = entry.findtext("atom:published", default="", namespaces=NS)
                published = datetime.fromisoformat(published_text.replace("Z", "+00:00")) if published_text else None
                categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", NS)]
                if title and url:
                    batch.append(RadarItem(title=title, url=url, source="arXiv", summary=summary, published_at=published, tags=["paper", "arxiv", *categories], raw={"query": query, "categories": categories}))
            latency = time.perf_counter() - start
            results.append(CollectorResult(source="arXiv", items=batch, status="OK", latency_seconds=latency, details={"query": query}))
            print(f"[collector:arxiv] {query}: OK {len(batch)} {latency:.2f}s")
        except Exception as exc:
            latency = time.perf_counter() - start
            results.append(CollectorResult(source="arXiv", items=[], status="FAIL", latency_seconds=latency, error=str(exc), details={"query": query}))
            print(f"[collector:arxiv] {query}: FAIL {exc}")
    return results
