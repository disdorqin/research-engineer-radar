from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from radar.models import RadarItem
from radar.processing.normalize import clean_text

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _fetch_text(url: str, timeout: int = 12) -> str:
    request = Request(url, headers={"User-Agent": "research-engineer-radar/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None


def _child_text(node: ET.Element, *names: str) -> str:
    for name in names:
        child = node.find(name, ATOM_NS) if ":" in name else node.find(name)
        if child is not None and child.text:
            return clean_text(child.text)
    return ""


def parse_feed(xml_text: str, source_name: str) -> list[RadarItem]:
    root = ET.fromstring(xml_text)
    items: list[RadarItem] = []
    if root.tag.endswith("feed"):
        for entry in root.findall("atom:entry", ATOM_NS):
            title = _child_text(entry, "atom:title")
            link_node = entry.find("atom:link", ATOM_NS)
            link = link_node.attrib.get("href", "") if link_node is not None else ""
            summary = _child_text(entry, "atom:summary", "atom:content")
            published = _parse_date(_child_text(entry, "atom:published", "atom:updated"))
            if title and link:
                items.append(RadarItem(title=title, url=link, source=source_name, summary=summary, published_at=published))
        return items
    channel = root.find("channel")
    if channel is not None:
        for entry in channel.findall("item"):
            title = _child_text(entry, "title")
            link = _child_text(entry, "link")
            summary = _child_text(entry, "description")
            published = _parse_date(_child_text(entry, "pubDate", "date"))
            if title and link:
                items.append(RadarItem(title=title, url=link, source=source_name, summary=summary, published_at=published))
    return items


def collect_rss(sources: list[dict], limit_per_source: int = 12) -> list[RadarItem]:
    collected: list[RadarItem] = []
    for source in sources:
        name = source["name"]
        url = source["url"]
        try:
            collected.extend(parse_feed(_fetch_text(url), name)[:limit_per_source])
        except Exception as exc:
            collected.append(RadarItem(title=f"Collector error: {name}", url=url, source="Radar System", summary=str(exc), published_at=datetime.now(timezone.utc), tags=["collector-error"]))
    return collected
