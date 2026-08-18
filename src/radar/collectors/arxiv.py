from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from radar.models import RadarItem
from radar.processing.normalize import clean_text

NS = {"atom": "http://www.w3.org/2005/Atom"}


def collect_arxiv(queries: list[str], per_query: int = 8) -> list[RadarItem]:
    results: list[RadarItem] = []
    for query in queries:
        params = urlencode({"search_query": query, "start": 0, "max_results": per_query, "sortBy": "submittedDate", "sortOrder": "descending"})
        request = Request(f"https://export.arxiv.org/api/query?{params}", headers={"User-Agent": "research-engineer-radar/0.1"})
        try:
            with urlopen(request, timeout=20) as response:
                root = ET.fromstring(response.read())
            for entry in root.findall("atom:entry", NS):
                title = clean_text(entry.findtext("atom:title", default="", namespaces=NS))
                summary = clean_text(entry.findtext("atom:summary", default="", namespaces=NS))
                url = entry.findtext("atom:id", default="", namespaces=NS)
                published_text = entry.findtext("atom:published", default="", namespaces=NS)
                published = datetime.fromisoformat(published_text.replace("Z", "+00:00")) if published_text else None
                if title and url:
                    results.append(RadarItem(title=title, url=url, source="arXiv", summary=summary, published_at=published, tags=["paper", "arxiv"], raw={"query": query}))
        except Exception as exc:
            results.append(RadarItem(title=f"arXiv collector error: {query}", url="https://arxiv.org", source="Radar System", summary=str(exc), tags=["collector-error"]))
    return results
