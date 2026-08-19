# Architecture

Research Engineer Radar is a small, config-driven daily intelligence pipeline for AI Research Engineer growth.

## Design goal

The project should optimize for final recommendation quality, not raw crawl volume.

The desired daily flow is:

```text
collect many candidates
  -> isolate source failures
  -> normalize and deduplicate
  -> rank cheaply and explainably
  -> balance sources
  -> enrich only the shortlist
  -> optionally ask an LLM for personal relevance analysis
  -> output 5-10 actionable items
```

## Runtime flow

```text
main.run
  ├── collect_rss
  ├── collect_sitemaps
  ├── collect_huggingface_papers
  ├── collect_github
  ├── collect_arxiv
  ├── collect_hacker_news
  ↓
CollectorResult[]
  ↓
RunStats / Source Health
  ↓
deduplicate_items
  ↓
SeenState.observe
  ↓
rank_items
  ↓
source_balanced_select(max_candidates)
  ↓
filter already-pushed items
  ↓
enrich_shortlist
  ↓
analyze_shortlist
  ↓
source_balanced_select(top_n)
  ↓
render_digest
  ↓
publish_enabled
  ↓
SeenState.mark_pushed + save
```

## Source Health

Collectors return `CollectorResult`:

```python
CollectorResult(
    source="OpenAI",
    items=[...],
    status="OK" | "FAIL" | "SKIP",
    latency_seconds=1.2,
    error="",
    details={...},
)
```

Collector errors must never become normal `RadarItem` candidates. They are logged and rendered in the digest run stats.

## State

State is file-based in v1:

```text
data/seen.json
```

Each record tracks:

- id
- title
- url
- source
- first_seen_at
- last_seen_at
- pushed
- pushed_at

`seen != pushed`.

A candidate can be observed but not pushed. It can still be considered again later if ranking/profile changes.

## Ranking

Deterministic ranking is intentionally cheap and explainable. It considers:

- topic alignment;
- engineering value;
- source quality;
- freshness;
- actionability;
- current-project transferability;
- GitHub/community signal;
- hype penalty;
- old popular GitHub repository penalty.

Ranking weights are configured in `config/radar.json`.

## Source balance

Source balancing happens twice:

1. before expensive enrichment/LLM, to prevent a source-order or source-volume bias;
2. before final Top N, to avoid a report that is effectively all arXiv or all GitHub.

It is a soft quota, not a rigid category quota. Very high scoring items can still pass through.

## Shortlist enrichment

Only shortlisted items are enriched:

- GitHub: repo metadata and README excerpt when `GITHUB_TOKEN` is available;
- blog/RSS items: main page text extraction with size limits;
- arXiv/HuggingFace: title + abstract/summary are usually enough for v1.

This controls cost, latency, and failure surface.

## LLM analysis

The LLM is optional and OpenAI-compatible.

Default target:

```text
LLM_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.5-flash
```

Expected JSON fields:

```json
{
  "relevance": 0,
  "engineering_value": 0,
  "novelty": 0,
  "actionability": 0,
  "project_transferability": 0,
  "what_it_is": "...",
  "why_it_matters": "...",
  "ability_tree_relation": "...",
  "current_project_relation": "...",
  "suggested_action": "精读 | 浏览 | 收藏 | 尝试",
  "experiment_idea": "..."
}
```

If the LLM is not configured or fails, the pipeline falls back to deterministic ranking.

## Publishing

Telegram is the only v1 production publisher.

The Markdown report in `reports/*.md` is the full version. Telegram can send a compact mobile-friendly version with chunking and retries.

## GitHub Actions

The daily workflow supports:

- `workflow_dispatch`;
- scheduled run at 08:30 Asia/Shanghai;
- unit tests before execution;
- optional LLM connectivity check;
- radar execution;
- artifact upload;
- state/report commit;
- concurrency guard.
