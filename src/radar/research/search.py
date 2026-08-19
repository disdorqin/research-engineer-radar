from __future__ import annotations

import heapq
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from radar.collectors.arxiv import collect_arxiv
from radar.collectors.github_search import collect_github
from radar.models import RadarItem
from radar.query.planner import QueryPlan
from radar.research.observability import ResearchTrace, append_trace
from radar.research.provenance import canonicalize_url, host_of, infer_relation, is_noise_link, kind_of


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
    published_at: str = ""
    metadata: dict = field(default_factory=dict)


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
    trace: ResearchTrace | None = None


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


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self.description = ""
        self._href = ""
        self._parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
            self._title_parts = []
        if tag == "meta":
            name = (values.get("name") or values.get("property") or "").lower()
            if name in {"description", "og:description", "twitter:description"} and not self.description:
                self.description = unescape(values.get("content") or "").strip()
        if tag != "a":
            return
        href = values.get("href") or ""
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            return
        self._href = urljoin(self.base_url, href)
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self.title = unescape(" ".join(self._title_parts)).strip()
            self._in_title = False
        if tag == "a" and self._href:
            anchor = unescape(" ".join(self._parts)).strip()
            self.links.append((self._href, anchor))
            self._href = ""
            self._parts = []


_PRIMARY_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "ai.google.dev", "research.google",
    "ai.meta.com", "engineering.fb.com", "developer.nvidia.com", "nvidia.com",
    "netflixtechblog.com", "blog.cloudflare.com", "huggingface.co", "arxiv.org", "github.com",
    "microsoft.com", "research.microsoft.com", "aws.amazon.com", "engineering.atspotify.com",
}


def _primary_score(url: str, source: str, config: dict) -> float:
    host = host_of(url)
    configured = {
        str(v).lower().removeprefix("www.")
        for v in config.get("interactive_search", {}).get("primary_domains", [])
    }
    domains = _PRIMARY_DOMAINS | configured
    if any(host == domain or host.endswith("." + domain) for domain in domains):
        if host in {"github.com", "arxiv.org"}:
            return 0.92
        return 0.97
    if source in {"arXiv", "GitHub Search", "HuggingFace Papers", "X API", "YouTube API"}:
        return 0.88
    if source == "Hacker News":
        return 0.35
    if kind_of(url, source) in {"x", "video"}:
        return 0.62
    return 0.45


def _terms(plan: QueryPlan) -> list[str]:
    values = [plan.topic, *plan.keywords, *plan.must_include]
    return [v.lower().strip() for v in values if v and len(v.strip()) > 1]


def _relevance(text: str, plan: QueryPlan) -> float:
    haystack = text.lower()
    excluded = [v.lower() for v in plan.exclude_terms if v]
    if excluded and any(term in haystack for term in excluded):
        return 0.02
    terms = _terms(plan)
    if not terms:
        return 0.2
    phrase_hits = sum(1 for term in terms if term in haystack)
    token_hits = 0
    unique_tokens: set[str] = set()
    for term in terms:
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_.+-]{2,}|[\u4e00-\u9fff]{2,}", term):
            token = token.lower()
            if token not in unique_tokens and token in haystack:
                unique_tokens.add(token)
                token_hits += 1
    return min(1.0, phrase_hits * 0.25 + token_hits * 0.075)


def _score_node(node: SourceNode, plan: QueryPlan, config: dict) -> float:
    text = f"{node.title} {node.summary} {node.url}"
    relevance = _relevance(text, plan)
    node.primary_score = _primary_score(node.url, node.source, config)
    primary_weight = 0.42 if plan.primary_only or plan.intent in {"primary_sources", "source_trace"} else 0.26
    score = relevance * (0.70 - primary_weight / 3) + node.primary_score * primary_weight + 0.08
    if node.kind in {"paper", "code"}:
        score += 0.06
    if node.kind in {"x", "video"} and plan.intent in {"hot", "latest", "source_trace"}:
        score += 0.04
    if node.relation in {"cites", "implements", "announces", "follow_up"}:
        score += 0.06
    score -= 0.035 * node.depth
    if plan.exclude_terms and any(term.lower() in text.lower() for term in plan.exclude_terms):
        score -= 0.45
    return round(max(0.0, min(score, 1.0)), 4)


def _decode_ddg_url(url: str) -> str:
    value = unescape((url or "").strip())
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if "duckduckgo.com" in (parsed.hostname or ""):
        from urllib.parse import parse_qs, unquote
        target = (parse_qs(parsed.query).get("uddg") or [""])[0]
        if target:
            value = unquote(target)
    return canonicalize_url(value)


def _ddg_search(query: str, limit: int, timeout: int) -> list[SourceNode]:
    request = Request(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        headers={"User-Agent": "Mozilla/5.0 ResearchNavigator/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        html = response.read(1_500_000).decode("utf-8", errors="ignore")
    parser = _DDGParser()
    parser.feed(html)
    nodes: list[SourceNode] = []
    for row in parser.results[:limit]:
        url = _decode_ddg_url(row["url"])
        if is_noise_link(url, row["title"]):
            continue
        nodes.append(SourceNode(title=row["title"], url=url, source="Web Search", summary=row.get("summary", ""), kind=kind_of(url)))
    return nodes


def _searxng_search(query: str, limit: int, config: dict, timeout: int) -> list[SourceNode]:
    cfg = config.get("interactive_search", {})
    env_name = cfg.get("searxng_base_url_env", "SEARXNG_BASE_URL")
    base = os.getenv(env_name, "").strip() or str(cfg.get("searxng_base_url", "")).strip()
    if not base:
        return []
    endpoint = base.rstrip("/") + "/search?" + urlencode({"q": query, "format": "json", "language": "all", "safesearch": 1})
    request = Request(endpoint, headers={"User-Agent": "ResearchNavigator/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    nodes: list[SourceNode] = []
    for row in payload.get("results", [])[:limit]:
        url = canonicalize_url(str(row.get("url") or ""))
        title = str(row.get("title") or url)
        if not url or is_noise_link(url, title):
            continue
        nodes.append(SourceNode(title=title, url=url, source="SearXNG", summary=str(row.get("content") or ""), kind=kind_of(url), published_at=str(row.get("publishedDate") or "")))
    return nodes


def _web_search(query: str, limit: int, config: dict, timeout: int) -> tuple[list[SourceNode], str]:
    try:
        nodes = _searxng_search(query, limit, config, timeout)
        if nodes:
            return nodes, "SearXNG"
    except Exception as exc:
        print(f"[provider:searxng] fallback: {exc}")
    return _ddg_search(query, limit, timeout), "Web Search"


def _hn_search(query: str, limit: int, timeframe_days: int, timeout: int) -> list[SourceNode]:
    numeric_filters = ""
    if timeframe_days > 0:
        created_after = int((datetime.now(timezone.utc) - timedelta(days=timeframe_days)).timestamp())
        numeric_filters = f"&numericFilters=created_at_i>{created_after}"
    endpoint = f"https://hn.algolia.com/api/v1/search_by_date?query={quote_plus(query)}&tags=story&hitsPerPage={limit}{numeric_filters}"
    request = Request(endpoint, headers={"User-Agent": "research-navigator/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    nodes: list[SourceNode] = []
    for hit in payload.get("hits", [])[:limit]:
        title = hit.get("title") or "Hacker News discussion"
        story_url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        url = canonicalize_url(hit.get("url") or story_url)
        summary = f"HN points={hit.get('points', 0)} comments={hit.get('num_comments', 0)} · discussion={story_url}"
        nodes.append(SourceNode(title=title, url=url, source="Hacker News", summary=summary, kind=kind_of(url, "Hacker News"), published_at=str(hit.get("created_at") or ""), metadata={"discussion_url": story_url}))
    return nodes


def _x_search(query: str, limit: int, timeframe_days: int, config: dict, timeout: int) -> list[SourceNode]:
    env_name = config.get("interactive_search", {}).get("x_bearer_token_env", "X_BEARER_TOKEN")
    token = os.getenv(env_name, "").strip()
    if not token:
        return []
    q = re.sub(r"\s+", " ", query).strip()
    if "-is:retweet" not in q:
        q = f"{q} -is:retweet"
    params = {"query": q[:500], "max_results": max(10, min(100, limit)), "tweet.fields": "created_at,public_metrics,author_id", "expansions": "author_id", "user.fields": "username,name,verified", "sort_order": "recency"}
    if timeframe_days < 7:
        start = datetime.now(timezone.utc) - timedelta(days=max(1, timeframe_days))
        params["start_time"] = start.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    request = Request("https://api.x.com/2/tweets/search/recent?" + urlencode(params), headers={"Authorization": f"Bearer {token}", "User-Agent": "ResearchNavigator/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    users = {str(u.get("id")): u for u in payload.get("includes", {}).get("users", [])}
    nodes: list[SourceNode] = []
    for post in payload.get("data", [])[:limit]:
        user = users.get(str(post.get("author_id")), {})
        username = user.get("username") or "i"
        post_id = str(post.get("id") or "")
        if not post_id:
            continue
        url = f"https://x.com/{username}/status/{post_id}"
        metrics = post.get("public_metrics") or {}
        summary = str(post.get("text") or "")
        if metrics:
            summary += f" · likes={metrics.get('like_count', 0)} reposts={metrics.get('retweet_count', 0)} replies={metrics.get('reply_count', 0)}"
        nodes.append(SourceNode(title=f"@{username}: {summary[:100]}", url=url, source="X API", summary=summary, kind="x", published_at=str(post.get("created_at") or ""), metadata={"verified": bool(user.get("verified")), "metrics": metrics}))
    return nodes


def _youtube_search(query: str, limit: int, timeframe_days: int, config: dict, timeout: int) -> list[SourceNode]:
    env_name = config.get("interactive_search", {}).get("youtube_api_key_env", "YOUTUBE_API_KEY")
    key = os.getenv(env_name, "").strip()
    if not key:
        return []
    published_after = (datetime.now(timezone.utc) - timedelta(days=max(1, timeframe_days))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": min(50, max(1, limit)), "order": "date" if timeframe_days <= 14 else "relevance", "publishedAfter": published_after, "relevanceLanguage": "en", "key": key}
    request = Request("https://www.googleapis.com/youtube/v3/search?" + urlencode(params), headers={"User-Agent": "ResearchNavigator/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    nodes: list[SourceNode] = []
    for row in payload.get("items", [])[:limit]:
        video_id = (row.get("id") or {}).get("videoId")
        snippet = row.get("snippet") or {}
        if not video_id:
            continue
        nodes.append(SourceNode(title=unescape(str(snippet.get("title") or "YouTube video")), url=f"https://www.youtube.com/watch?v={video_id}", source="YouTube API", summary=unescape(str(snippet.get("description") or "")), kind="video", published_at=str(snippet.get("publishedAt") or ""), metadata={"channel": snippet.get("channelTitle") or ""}))
    return nodes


def _from_radar_item(item: RadarItem) -> SourceNode:
    published = item.published_at.isoformat() if item.published_at else ""
    url = canonicalize_url(item.url)
    return SourceNode(title=item.title, url=url, source=item.source, summary=item.summary, kind=kind_of(url, item.source), published_at=published, metadata=dict(item.raw))


def _fresh_enough(node: SourceNode, plan: QueryPlan) -> bool:
    if not node.published_at:
        return True
    try:
        dt = datetime.fromisoformat(node.published_at.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(days=plan.timeframe_days + 1)
    except Exception:
        return True


def _seed_search(plan: QueryPlan, config: dict, trace: ResearchTrace) -> tuple[list[SourceNode], list[str]]:
    nodes: list[SourceNode] = []
    warnings: list[str] = []
    cfg = config.get("interactive_search", {})
    timeout = int(cfg.get("provider_timeout_seconds", 15))
    per_provider = int(cfg.get("per_provider_results", 5))
    queries = plan.queries[:4] or [plan.topic]

    if "web" in plan.platforms:
        for query in queries[:3]:
            try:
                batch, provider_name = _web_search(query, per_provider, config, timeout)
                nodes.extend(batch)
                trace.provider(provider_name, len(batch))
            except Exception as exc:
                warnings.append(f"web:{type(exc).__name__}")
                trace.event("provider_error", f"web:{exc}")

    if "arxiv" in plan.platforms:
        specs = [{"query": f'all:"{query.replace(chr(34), "")}"', "limit": per_provider} for query in queries[:2]]
        for batch in collect_arxiv(specs):
            converted = [_from_radar_item(item) for item in batch.items]
            converted = [n for n in converted if _fresh_enough(n, plan)]
            nodes.extend(converted)
            trace.provider("arXiv", len(converted))
            if not batch.ok:
                warnings.append(f"arxiv:{batch.error}")

    if "github" in plan.platforms:
        specs = [{"query": query, "lookback_days": plan.timeframe_days, "limit": per_provider} for query in queries[:2]]
        for batch in collect_github(specs, default_lookback_days=plan.timeframe_days):
            converted = [_from_radar_item(item) for item in batch.items]
            nodes.extend(converted)
            trace.provider("GitHub", len(converted))
            if not batch.ok:
                warnings.append(f"github:{batch.error}")

    if "hacker_news" in plan.platforms:
        for query in queries[:2]:
            try:
                batch = _hn_search(query, per_provider, plan.timeframe_days, timeout)
                nodes.extend(batch)
                trace.provider("Hacker News", len(batch))
            except Exception as exc:
                warnings.append(f"hn:{type(exc).__name__}")

    if "x" in plan.platforms:
        for query in queries[:2]:
            try:
                batch = _x_search(query, per_provider, plan.timeframe_days, config, timeout)
                if not batch and cfg.get("social_web_fallback", True):
                    batch, _ = _web_search(f"site:x.com {query}", min(4, per_provider), config, timeout)
                    for node in batch:
                        node.source = "X Web Search"
                        node.kind = "x"
                nodes.extend(batch)
                trace.provider("X", len(batch))
            except Exception as exc:
                warnings.append(f"x:{type(exc).__name__}")

    if "youtube" in plan.platforms:
        for query in queries[:2]:
            try:
                batch = _youtube_search(query, per_provider, plan.timeframe_days, config, timeout)
                if not batch and cfg.get("social_web_fallback", True):
                    batch, _ = _web_search(f"site:youtube.com {query}", min(4, per_provider), config, timeout)
                    for node in batch:
                        node.source = "YouTube Web Search"
                        node.kind = "video"
                nodes.extend(batch)
                trace.provider("YouTube", len(batch))
            except Exception as exc:
                warnings.append(f"youtube:{type(exc).__name__}")

    filtered: list[SourceNode] = []
    for node in nodes:
        node.url = canonicalize_url(node.url)
        if not node.url or is_noise_link(node.url, node.title):
            continue
        if plan.exclude_terms and any(term.lower() in f"{node.title} {node.summary}".lower() for term in plan.exclude_terms):
            continue
        filtered.append(node)
    trace.event("seed_search", f"raw={len(nodes)} filtered={len(filtered)}")
    return filtered, warnings


def _fetch_page(url: str, timeout: int) -> tuple[str, str, list[tuple[str, str]]]:
    host = host_of(url)
    if host in {"x.com", "twitter.com", "youtube.com", "youtu.be", "news.ycombinator.com"}:
        return "", "", []
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ResearchNavigator/1.0", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type:
            return "", "", []
        html = response.read(1_800_000).decode("utf-8", errors="ignore")
    parser = _PageParser(url)
    parser.feed(html)
    return parser.title, parser.description, parser.links


def _link_value(url: str, anchor: str, parent: SourceNode, plan: QueryPlan, config: dict) -> float:
    target = canonicalize_url(url)
    if is_noise_link(target, anchor):
        return 0.0
    target_kind = kind_of(target)
    relation = infer_relation(parent.url, target, anchor, parent.kind, target_kind)
    score = _relevance(f"{anchor} {target}", plan) * 0.52
    if target_kind in {"paper", "code", "x", "video"}:
        score += 0.28
    if relation in {"cites", "implements", "announces", "follow_up"}:
        score += 0.18
    if host_of(target) != host_of(parent.url):
        score += 0.08
    primary = _primary_score(target, host_of(target), config)
    score += primary * 0.14
    return min(score, 1.0)


def _dedupe_nodes(nodes: list[SourceNode]) -> list[SourceNode]:
    by_url: dict[str, SourceNode] = {}
    for node in nodes:
        node.url = canonicalize_url(node.url)
        if not node.url or is_noise_link(node.url, node.title):
            continue
        existing = by_url.get(node.url)
        if existing is None:
            by_url[node.url] = node
            continue
        if len(node.summary) > len(existing.summary):
            existing.summary = node.summary
        if node.score > existing.score:
            existing.score = node.score
            existing.primary_score = max(existing.primary_score, node.primary_score)
        if not existing.published_at and node.published_at:
            existing.published_at = node.published_at
    return list(by_url.values())


def _expand_graph(result: ResearchResult, config: dict) -> int:
    cfg = config.get("interactive_search", {})
    max_nodes = int(cfg.get("max_graph_nodes", 36))
    max_fetches = int(cfg.get("max_graph_fetches", 10))
    links_per_page = int(cfg.get("links_per_page", 5))
    min_link_value = float(cfg.get("min_link_value", 0.34))
    timeout = int(cfg.get("crawl_timeout_seconds", 12))

    seen = {node.url for node in result.nodes}
    crawled: set[str] = set()
    frontier: list[tuple[float, int, str]] = []
    by_url = {node.url: node for node in result.nodes}
    seq = 0
    for node in result.nodes:
        heapq.heappush(frontier, (-node.score, seq, node.url))
        seq += 1

    fetches = 0
    while frontier and len(result.nodes) < max_nodes and fetches < max_fetches:
        _, _, parent_url = heapq.heappop(frontier)
        parent = by_url.get(parent_url)
        if parent is None or parent.url in crawled or parent.depth >= result.plan.depth:
            continue
        crawled.add(parent.url)
        try:
            page_title, description, links = _fetch_page(parent.url, timeout)
            fetches += 1
        except Exception as exc:
            result.warnings.append(f"crawl:{host_of(parent.url)}:{type(exc).__name__}")
            continue

        if page_title and (not parent.title or parent.title == parent.url):
            parent.title = page_title
        if description and (not parent.summary or parent.summary.startswith("由《")):
            parent.summary = description

        ranked_links = sorted(((canonicalize_url(url), anchor, _link_value(url, anchor, parent, result.plan, config)) for url, anchor in links), key=lambda row: row[2], reverse=True)
        added = 0
        for target, anchor, value in ranked_links:
            if value < min_link_value or target in seen or is_noise_link(target, anchor):
                continue
            target_kind = kind_of(target)
            relation = infer_relation(parent.url, target, anchor, parent.kind, target_kind)
            node = SourceNode(title=(re.sub(r"\s+", " ", anchor).strip() or target)[:240], url=target, source=host_of(target) or "linked source", summary=f"由《{parent.title[:80]}》发现 · {relation}", kind=target_kind, depth=parent.depth + 1, discovered_from=parent.url, relation=relation)
            node.score = _score_node(node, result.plan, config)
            result.nodes.append(node)
            by_url[node.url] = node
            result.edges.append(SourceEdge(parent.url, node.url, relation))
            seen.add(node.url)
            heapq.heappush(frontier, (-node.score, seq, node.url))
            seq += 1
            added += 1
            if added >= links_per_page or len(result.nodes) >= max_nodes:
                break
    return fetches


def research(plan: QueryPlan, config: dict, seed_url: str | None = None) -> ResearchResult:
    trace = ResearchTrace.start(plan.original_query)
    warnings: list[str] = []
    if seed_url:
        seed_url = canonicalize_url(seed_url)
        seed = SourceNode(title=seed_url, url=seed_url, source=host_of(seed_url) or "seed", kind=kind_of(seed_url), score=1.0)
        nodes = [seed]
        trace.provider("seed", 1)
    else:
        nodes, warnings = _seed_search(plan, config, trace)

    nodes = _dedupe_nodes(nodes)
    for node in nodes:
        node.score = _score_node(node, plan, config)
    nodes.sort(key=lambda node: node.score, reverse=True)

    result = ResearchResult(plan=plan, nodes=nodes, warnings=warnings, trace=trace)
    fetches = _expand_graph(result, config) if plan.depth > 0 and result.nodes else 0
    result.nodes = _dedupe_nodes(result.nodes)
    for node in result.nodes:
        node.score = _score_node(node, plan, config)
    if plan.primary_only:
        result.nodes.sort(key=lambda node: (node.primary_score >= 0.75, node.score), reverse=True)
    else:
        result.nodes.sort(key=lambda node: node.score, reverse=True)

    trace.finish(len(result.nodes), len(result.edges), fetches, result.warnings)
    trace_path = config.get("interactive_search", {}).get("trace_path", "data/research_traces.jsonl")
    try:
        append_trace(trace_path, trace)
    except Exception as exc:
        print(f"[trace] write failed: {exc}")
    print(f"[research] trace={trace.trace_id} topic={plan.topic!r} nodes={len(result.nodes)} edges={len(result.edges)} fetches={fetches} duration_ms={trace.duration_ms}")
    return result
