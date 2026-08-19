# Gap Analysis

## Initial verified gap

The local `research-engineer-radar/` directory was not an independent Git checkout. It was an untracked child directory inside the parent `vibe_coding` repository.

The real GitHub repository was cloned separately into `research-engineer-radar-remote/`, and all implementation work in this round was applied there.

## Gap: collector failures polluted candidates

Old behavior:

- Collector exceptions were converted into fake `RadarItem` objects such as `Collector error: ...`.
- Ranking had to filter these later.

Current behavior:

- Collectors return `CollectorResult`.
- Errors go to Source Health / RunStats.
- Failed collectors produce zero candidate items.

## Gap: GitHub query date was hard-coded

Old behavior:

```text
pushed:>2026-01-01
```

Current behavior:

- GitHub query specs support `lookback_days`.
- `build_github_query()` dynamically adds `pushed:>{since}`.
- Tests assert that the old hard-coded date is not used.

## Gap: source order and source imbalance

Old behavior:

- Collector outputs were concatenated and then truncated.
- Earlier sources had an implicit advantage.

Current behavior:

- All items are collected and deduplicated first.
- Items are ranked before truncation.
- A soft source-balanced selector is applied before enrichment and again before final Top N.

## Gap: ranking was too close to keyword counting

Current deterministic ranking includes:

- topic alignment;
- engineering value;
- source quality;
- freshness;
- actionability;
- project transferability;
- GitHub signal;
- hype penalty;
- old popular GitHub repo penalty.

## Gap: no Source Health

Current digest includes a Source Health section with per-source status, item count, and latency.

## Gap: no shortlist enrichment

Current behavior:

- Only shortlist items are enriched.
- GitHub enrichment uses API + README when `GITHUB_TOKEN` is present.
- Web enrichment extracts article/main text with length limits.

## Gap: HuggingFace RSS was not reliable

Verified local dry-run showed:

```text
HuggingFace Papers RSS -> HTTP 401 Unauthorized
```

Current behavior:

- Use `https://huggingface.co/api/daily_papers` instead.
- Latest dry-run fetched 10 HuggingFace Papers items successfully.

## Gap: Hacker News collector was too slow

Initial HN implementation used official topstories with N+1 requests and took more than 80 seconds.

Current behavior:

- Use HN Algolia with several focused queries.
- Latest dry-run fetched 8 items in about 3.34 seconds.

## Gap: LLM had weak schema

Current LLM output schema includes relevance, engineering value, novelty, actionability, project transferability, detailed explanations, suggested action, and optional experiment idea.

LLM failure is non-fatal.

## Gap: tests were too thin

Old verified tests:

```text
6 tests passed
```

Current verified tests:

```text
16 tests passed
```

Coverage includes parsing, canonicalization, deduplication, state, dynamic GitHub dates, ranking, source balance, LLM JSON parsing/fallback, Telegram splitting, digest rendering, collector failure isolation, and config loading.

## Remaining gaps

- Agnes could not be truly tested locally because `LLM_API_KEY` is not configured.
- Telegram could not be truly sent locally because `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are not configured.
- GitHub Actions manual trigger still needs to be run after secrets are configured.
- Semantic Scholar / Crossref / Papers with Code are Phase 2; not added yet to avoid widening scope before v1 quality stabilizes.
