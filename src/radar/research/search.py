from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from radar.collectors.arxiv import collect_arxiv
from radar.collectors.github_search import collect_github
from radar.models import RadarItem
from radar.processing.normalize import deduplicate_items
from radar.query.planner import QueryPlan


@dataclass(slots=True)
class SourceNode:
    title: str
    url: str
    source: str
    summary: str = ""
    kind: str = "web"
    score: float = 0.0
    primary_score: float = 0.0
    depth: int = 0
    discovered_from: str = ""
    relation: str = "seed"


@dataclass(slots=True)
class SourceEdge:
    source_url: str
    target_url: str
    relation: str = "links_to"


@dataclass(slots=True)
class ResearchResult:
    plan: QueryPlan
    nodes: list[SourceNode] = field(default_factory=list)
    edges: list[SourceEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _DDGParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict] = []
        self._mode = ""
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = values.get("class") or ""
        if tag == "a" and "result__a" in classes:
            self._mode = "title"
            self._href = values.get("href") or ""
            self._parts = []
        elif tag in {"a", "div"} and "result__snippet" in classes:
            self._mode = "snippet"
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._mode:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._mode == "title" and tag == "a":
            title = unescape(" ".join(self._parts)).strip()
            if title and self._href:
                self.results.append({"title": title, "url": self._href, "summary": ""})
            self._mode = ""
            self._parts = []
        elif self._mode == "snippet" and tag in {"a", "div"}:
            if self.results:
                self.results[-1]["summary"] = unescape(" ".join(self._parts)).strip()
            self._mode = ""
            self._parts = []


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            return
        self._href = urljoin(self.base_url, href)
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            text = unescape(" ".join(self._parts)).strip()
            self.links.append((self._href, text))
            self._href = ""
            self._parts = []


_PRIMARY_DOMAINS = {
    "openai.com",
    "anthropic.com",
    "deepmind.google",
    "ai.google.dev",
    "research.google",
    "engineering.fb.com",
    "ai.meta.com",
    "developer.nvidia.com",
    "nvidia.com",
    "netflixtechblog.com",
    "blog.cloudflare.com",
    "huggingface.co",
    "arxiv.org",
    "github.com",
}


def _clean_url(url: str) -> str:
    url = unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        target = (query.get("uddg") or [""])[0]
        if target:
            url = unquote(target)
    return url


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _kind(url: str, source: str = "") -> str:
    host = _host(url)
    if "arxiv.org" in host:
        return "paper"
    if "github.com" in host:
        return "code"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com"):
        return "x"
    if "youtube.com" in host or "youtu.be" in host:
        return "video"
    if source == "Hacker News":
        return "discussion"
    return "web"


def _primary_score(url: str, source: str, config: dict) -> float:
    host = _host(url)
    configured = {str(v).lower().removeprefix("www.") for v in config.get("interactive_search", {}).get("primary_domains", [])}
    domains = _PRIMARY_DOMAINS | configured
    if any(host == domain or host.endswith("." + domain) for domain in domains):
        return 0.96 if host not in {"github.com", "arxiv.org"} else 0.92
    if source in {"arXiv", "GitHub Search", "HuggingFace Papers"}:
        return 0.9
    if _kind(url, source) in {"x", "video"}:
        return 0.58
    if source == "Hacker News":
        return 0.35
    return 0.45


def _relevance(text: str, plan: QueryPlan) -> float:
    haystack = text.lower()
    terms = [plan.topic, *plan.keywords]
    terms = [t.lower().strip() for t in terms if t and len(t.strip()) > 1]
    if not terms:
        return 0.2
    hits = sum(1 for term in terms if term in haystack)
    token_hits = 0
    for term in terms:
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_.+-]{2,}|[\u4e00-\u9fff]{2,}", term):
            if token.lower() in haystack:
                token_hits += 1
    return min(1.0, hits * 0.28 + token_hits * 0.09)


def _score_node(node: SourceNode, plan: QueryPlan, config: dict) -> float:
    relevance = _relevance(f"{node.title} {node.summary} {node.url}", plan)
    node.primary_score = _primary_score(node.url, node.source, config)
    depth_penalty = 0.05 * node.depth
    primary_weight = 0.40 if plan.primary_only or plan.intent in {"primary_sources", "source_trace"} else 0.25
    score = relevance * (0.72 - primary_weight / 2) + node.primary_score * primary_weight + 0.12
    if node.kind in {"paper", "code"}:
        score += 0.06
    return round(max(0.0, min(score - depth_penalty, 1.0)), 4)


def _ddg_search(query: str, limit: int = 6) -> list[SourceNode]:
    request = Request(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        headers={"User-Agent": "Mozilla/5.0 ResearchNavigator/0.5"},
    )
    with urlopen(request, timeout=15) as response:
        html = response.read(1_500_000).decode("utf-8", errors="ignore")
    parser = _DDGParser()
    parser.feed(html)
    nodes = []
    for row in parser.results[:limit]:
        url = _clean_url(row["url"])
        if not url.startswith(("http://", "https://")):
            continue
        nodes.append(SourceNode(title=row["title"], url=url, source="Web Search", summary=row.get("summary", ""), kind=_kind(url)))
    return nodes


def _hn_search(query: str, limit: int = 5) -> list[SourceNode]:
    endpoint = f"https://hn.algolia.com/api/v1/search_by_date?query={quote_plus(query)}&tags=story&hitsPerPage={limit}"
    request = Request(endpoint, headers={"User-Agent": "research-engineer-radar/0.5"})
    with urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    nodes = []
    for hit in payload.get("hits", [])[:limit]:
        title = hit.get("title") or "Hacker News discussion"
        external = hit.get("url")
        story_url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        url = external or story_url
        summary = f"HN points={hit.get('points', 0)} comments={hit.get('num_comments', 0)} · discussion={story_url}"
        nodes.append(SourceNode(title=title, url=url, source="Hacker News", summary=summary, kind=_kind(url, "Hacker News")))
    return nodes


def _from_radar_item(item: RadarItem) -> SourceNode:
    return SourceNode(title=item.title, url=_clean_url(item.url), source=item.source, summary=item.summary, kind=_kind(item.url, item.source))


def _seed_search(plan: QueryPlan, config: dict) -> tuple[list[SourceNode], list[str]]:
    nodes: list[SourceNode] = []
    warnings: list[str] = []
    queries = plan.queries[:4] or [plan.topic]

    if "web" in plan.platforms:
        for query in queries[:3]:
            try:
                nodes.extend(_ddg_search(query, 5))
            except Exception as exc:
                warnings.append(f"web:{exc}")

    if "arxiv" in plan.platforms:
        specs = [{"query": f'all:"{query.replace(chr(34), "")}"', "limit": 4} for query in queries[:2]]
        for batch in collect_arxiv(specs):
            nodes.extend(_from_radar_item(item) for item in batch.items)
            if not batch.ok:
                warnings.append(f"arxiv:{batch.error}")

    if "github" in plan.platforms:
        specs = [{"query": query, "lookback_days": plan.timeframe_days, "limit": 4} for query in queries[:2]]
        for batch in collect_github(specs, default_lookback_days=plan.timeframe_days):
            nodes.extend(_from_radar_item(item) for item in batch.items)
            if not batch.ok:
                warnings.append(f"github:{batch.error}")

    if "hacker_news" in plan.platforms:
        for query in queries[:2]:
            try:
                nodes.extend(_hn_search(query, 4))
            except Exception as exc:
                warnings.append(f"hn:{exc}")

    if "x" in plan.platforms:
        for query in queries[:2]:
            try:
                nodes.extend(_ddg_search(f"site:x.com {query}", 4))
            except Exception as exc:
                warnings.append(f"x-search:{exc}")

    if "youtube" in plan.platforms:
        for query in queries[:2]:
            try:
                nodes.extend(_ddg_search(f"site:youtube.com {query}", 4))
            except Exception as exc:
                warnings.append(f"youtube-search:{exc}")

    return nodes, warnings


def _fetch_links(url: str) -> list[tuple[str, str]]:
    host = _host(url)
    if host in {"x.com", "twitter.com", "youtube.com", "youtu.be", "news.ycombinator.com"}:
        return []
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ResearchNavigator/0.5", "Accept": "text/html,*/*;q=0.8"})
    with urlopen(request, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type:
            return []
        html = response.read(1_500_000).decode("utf-8", errors="ignore")
    parser = _LinkParser(url)
    parser.feed(html)
    return parser.links


def _link_value(url: str, anchor: str, parent: SourceNode, plan: QueryPlan) -> float:
    host = _host(url)
    if not host:
        return 0.0
    score = _relevance(f"{anchor} {url}", plan) * 0.55
    if _kind(url) in {"paper", "code", "x", "video"}:
        score += 0.35
    if host == _host(parent.url):
        score += 0.08
    if any(token in (anchor + " " + url).lower() for token in ["paper", "arxiv", "code", "github", "source", "blog", "research", "author", "talk", "video"]):
        score += 0.12
    return min(score, 1.0)


def _expand_graph(result: ResearchResult, config: dict, max_nodes: int = 30) -> None:
    seen = {node.url for node in result.nodes}
    for depth in range(1, result.plan.depth + 1):
        frontier = [node for node in result.nodes if node.depth == depth - 1]
        frontier.sort(key=lambda node: node.score, reverse=True)
        for parent in frontier[:4]:
            if len(result.nodes) >= max_nodes:
                return
            try:
                links = _fetch_links(parent.url)
            except Exception as exc:
                result.warnings.append(f"crawl:{_host(parent.url)}:{exc}")
                continue
            ranked_links = sorted(
                ((url, anchor, _link_value(url, anchor, parent, result.plan)) for url, anchor in links),
                key=lambda row: row[2],
                reverse=True,
            )
            added = 0
            for url, anchor, value in ranked_links:
                url = _clean_url(url)
                if value < 0.28 or url in seen or not url.startswith(("http://", "https://")):
                    continue
                node = SourceNode(
                    title=anchor or url,
                    url=url,
                    source=_host(url) or "linked source",
                    summary=f"由《{parent.title[:80]}》中的链接发现",
                    kind=_kind(url),
                    depth=depth,
                    discovered_from=parent.url,
                    relation="links_to",
                )
                node.score = _score_node(node, result.plan, config)
                result.nodes.append(node)
                result.edges.append(SourceEdge(source_url=parent.url, target_url=url, relation="links_to"))
                seen.add(url)
                added += 1
                if added >= 4 or len(result.nodes) >= max_nodes:
                    break


def _dedupe_nodes(nodes: list[SourceNode]) -> list[SourceNode]:
    by_url: dict[str, SourceNode] = {}
    for node in nodes:
        key = node.url.rstrip("/")
        existing = by_url.get(key)
        if existing is None or len(node.summary) > len(existing.summary):
            by_url[key] = node
    return list(by_url.values())


def research(plan: QueryPlan, config: dict, seed_url: str | None = None) -> ResearchResult:
    started = time.perf_counter()
    if seed_url:
        seed = SourceNode(title=seed_url, url=seed_url, source=_host(seed_url) or "seed", kind=_kind(seed_url))
        seed.score = 1.0
        nodes, warnings = [seed], []
    else:
        nodes, warnings = _seed_search(plan, config)

    nodes = _dedupe_nodes(nodes)
    result = ResearchResult(plan=plan, nodes=nodes, warnings=warnings)
    for node in result.nodes:
        node.score = _score_node(node, plan, config)

    result.nodes.sort(key=lambda node: node.score, reverse=True)
    # Traverse links only from the strongest evidence. This is deliberately budgeted;
    # a research graph should expand useful branches, not crawl the whole Internet.
    if plan.depth > 0:
        _expand_graph(result, config, max_nodes=int(config.get("interactive_search", {}).get("max_graph_nodes", 30)))
    result.nodes = _dedupe_nodes(result.nodes)
    result.nodes.sort(key=lambda node: node.score, reverse=True)
    if plan.primary_only:
        primary = [node for node in result.nodes if node.primary_score >= 0.75]
        if primary:
            result.nodes = primary + [node for node in result.nodes if node not in primary]
    print(f"[research] topic={plan.topic!r} nodes={len(result.nodes)} edges={len(result.edges)} time={time.perf_counter()-started:.2f}s")
    return result
