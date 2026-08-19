from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from radar.models import RankedItem
from radar.processing.normalize import clean_text

SCRIPT_RE = re.compile(r"<script.*?</script>|<style.*?</style>", re.I | re.S)
BODY_RE = re.compile(r"<(article|main)[^>]*>(.*?)</\1>", re.I | re.S)


def _fetch_text(url: str, timeout: int = 10, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers={"User-Agent": "research-engineer-radar/0.3", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_json(url: str, timeout: int = 10, headers: dict[str, str] | None = None):
    return json.loads(_fetch_text(url, timeout, {"Accept": "application/vnd.github+json", **(headers or {})}))


def _extract_main_text(html_text: str, max_chars: int) -> str:
    html_text = SCRIPT_RE.sub(" ", html_text)
    matches = BODY_RE.findall(html_text)
    candidate = " ".join(match[1] for match in matches) if matches else html_text
    text = clean_text(candidate)
    return text[:max_chars]


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    split = urlsplit(url)
    if split.netloc.lower() != "github.com":
        return None
    parts = [part for part in split.path.split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _enrich_github(row: RankedItem, max_chars: int) -> None:
    owner_repo = _github_owner_repo(row.item.url)
    if owner_repo is None:
        return
    owner, repo = owner_repo
    headers: dict[str, str] = {}
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        row.reasons.append("enrichment_skipped:github_no_token")
        return
    headers["Authorization"] = f"Bearer {token}"
    repo_api = _fetch_json(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
    readme_text = ""
    try:
        readme = _fetch_json(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers)
        if readme.get("encoding") == "base64":
            readme_text = base64.b64decode(readme.get("content", "")).decode("utf-8", errors="replace")
            readme_text = clean_text(readme_text)[:max_chars]
    except Exception:
        readme_text = ""
    row.item.raw.update({
        "stars": repo_api.get("stargazers_count", row.item.raw.get("stars", 0)),
        "watchers": repo_api.get("subscribers_count", 0),
        "license": (repo_api.get("license") or {}).get("spdx_id", ""),
        "homepage": repo_api.get("homepage") or "",
        "topics": repo_api.get("topics") or row.item.raw.get("topics", []),
    })
    extra = []
    if repo_api.get("description"):
        extra.append(str(repo_api["description"]))
    if readme_text:
        extra.append("README: " + readme_text)
    if extra:
        row.item.summary = clean_text(row.item.summary + "\n" + "\n".join(extra))[: max_chars + 1000]
        row.reasons.append("enriched:github")


def _enrich_web(row: RankedItem, max_chars: int) -> None:
    if row.item.source in {"arXiv", "GitHub Search"}:
        return
    split = urlsplit(row.item.url)
    if split.scheme not in {"http", "https"}:
        return
    text = _extract_main_text(_fetch_text(row.item.url, timeout=10), max_chars)
    if len(text) > len(row.item.summary or ""):
        row.item.summary = text
        row.reasons.append("enriched:web")


def enrich_shortlist(items: list[RankedItem], config: dict) -> list[RankedItem]:
    enrich_cfg = config.get("enrichment", {})
    if not enrich_cfg.get("enabled", True):
        return items
    max_chars = int(enrich_cfg.get("max_chars", 4000))
    for row in items:
        try:
            if row.item.source == "GitHub Search":
                _enrich_github(row, max_chars)
            else:
                _enrich_web(row, max_chars)
        except Exception as exc:
            row.reasons.append(f"enrichment_failed:{type(exc).__name__}")
            print(f"[enrichment] failed for {row.item.title!r}: {exc}")
    return items
