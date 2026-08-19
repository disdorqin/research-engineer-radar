from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "ref_cta", "ref_loc", "source", "si", "feature",
    "gclid", "fbclid", "mc_cid", "mc_eid",
}

_NOISE_ANCHORS = {
    "sign in", "sign up", "log in", "login", "register", "notifications", "settings",
    "privacy", "privacy policy", "terms", "terms of service", "cookie", "cookies",
    "contact", "careers", "pricing", "sponsors", "skip to content", "home",
    "登录", "注册", "通知", "设置", "隐私", "条款", "联系我们", "招聘",
}

_NOISE_PATHS = {
    "/login", "/signup", "/register", "/sessions", "/notifications", "/settings",
    "/privacy", "/terms", "/contact", "/careers",
}

_RELATION_LABELS = {
    "seed": "发现",
    "links_to": "链接到",
    "cites": "引用",
    "implements": "代码/实现",
    "announces": "官方发布",
    "discusses": "讨论",
    "talks_about": "演讲/视频",
    "follow_up": "后续工作",
}


def canonicalize_url(url: str) -> str:
    value = unescape((url or "").strip())
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return value
    host = (parsed.hostname or "").lower()
    scheme = "https" if parsed.scheme == "http" and host in {"arxiv.org", "www.arxiv.org", "github.com", "www.github.com"} else parsed.scheme
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, "", urlencode(query, doseq=True), ""))


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def kind_of(url: str, source: str = "") -> str:
    host = host_of(url)
    path = urlparse(url).path.lower()
    if "arxiv.org" in host:
        return "paper"
    if "github.com" in host:
        if re.search(r"/(issues|discussions)/\d+", path):
            return "discussion"
        return "code"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com"):
        return "x"
    if "youtube.com" in host or "youtu.be" in host:
        return "video"
    if source == "Hacker News" or "news.ycombinator.com" in host:
        return "discussion"
    return "web"


def is_noise_link(url: str, anchor: str = "") -> bool:
    value = canonicalize_url(url)
    if not value.startswith(("http://", "https://")):
        return True
    parsed = urlparse(value)
    path = parsed.path.lower()
    host = host_of(value)
    anchor_norm = re.sub(r"\s+", " ", (anchor or "")).strip().lower()

    if anchor_norm in _NOISE_ANCHORS:
        return True
    if any(path == prefix or path.startswith(prefix + "/") for prefix in _NOISE_PATHS):
        return True
    if "github.com" in host:
        if path in {"/login", "/signup", "/notifications", "/settings"}:
            return True
        if path.startswith("/features/") and not re.search(r"/[^/]+/[^/]+", path):
            return True
    if any(token in anchor_norm for token in ["sign in", "sign up", "cookie policy", "privacy policy"]):
        return True
    return False


def infer_relation(parent_url: str, target_url: str, anchor: str = "", parent_kind: str = "", target_kind: str = "") -> str:
    text = f"{anchor} {target_url}".lower()
    target_kind = target_kind or kind_of(target_url)
    parent_kind = parent_kind or kind_of(parent_url)

    if any(token in text for token in ["follow-up", "follow up", "subsequent work", "后续", "followup"]):
        return "follow_up"
    if any(token in text for token in ["announcement", "announcing", "release notes", "official release", "官方发布", "发布"]):
        return "announces"
    if target_kind == "paper" or any(token in text for token in ["paper", "arxiv", "preprint", "论文", "study"]):
        return "cites"
    if target_kind == "code" or any(token in text for token in ["github", "source code", "code", "repository", "repo", "implementation", "代码", "仓库", "实现"]):
        return "implements"
    if target_kind == "x" or any(token in text for token in ["twitter", "x.com", "discussion", "thread", "作者讨论", "原帖"]):
        return "discusses"
    if target_kind == "video" or any(token in text for token in ["youtube", "talk", "presentation", "seminar", "演讲", "视频"]):
        return "talks_about"
    return "links_to"


def relation_label(relation: str) -> str:
    return _RELATION_LABELS.get(relation, relation)
