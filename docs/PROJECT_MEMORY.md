# Research Engineer Radar — Project Memory

Last updated: 2026-08-19

## Goal

Research Engineer Radar is not a generic AI news bot. It is a daily AI Research Engineer intelligence radar that should collect many candidates, filter aggressively, and return only 5-10 items worth the user's time.

The final output should explain:

- what the item is;
- why it matters;
- the key engineering point;
- how it relates to the AI Research Engineer ability tree;
- how it transfers to the current electricity/time-series forecasting project;
- whether to read, skim, save, or try a small experiment.

The quality metric is not candidate count or API count. The metric is whether the final 5-10 items are actually worth reading.

## Current direction weights

Configured in `config/radar.json`, not hard-coded:

- Engineering / systems optimization: 60%
- GitHub / AI infrastructure: 25%
- Papers / research: 15%

Current ability-tree focus includes AI Systems, ML Systems, training/inference, profiling, CPU/GPU/I/O, data pipeline, experiment infrastructure, evaluation, MLOps, AI Infra, Agent Engineering, Research Engineering, time-series forecasting, and electricity forecasting.

## Verified local state

On 2026-08-19, `D:\computer learning\vibe_coding` was verified as a parent Git repository with remote:

```text
https://github.com/disdorqin/cl-vibe-coding.git
```

The original local `research-engineer-radar/` directory was verified to be an untracked child directory inside that parent repo, not an independent checkout.

A correct independent checkout was cloned to:

```text
D:\computer learning\vibe_coding\research-engineer-radar-remote
```

with remote:

```text
https://github.com/disdorqin/research-engineer-radar.git
```

All active changes in this round were made in `research-engineer-radar-remote/`, not in the untracked old directory.

## Reference repositories

A sibling reference directory was created outside the main repo:

```text
D:\computer learning\vibe_coding\research-engineer-radar_refs
```

Cloned references:

- `OvOhao/auto-paper-collecter`
- `duanyytop/agents-radar`
- `backpropagation6/ai-news-scanner`
- `AutoLLM/ArxivDigest`

All four were verified as MIT-licensed. No full third-party repository was copied into this repo. See `THIRD_PARTY_NOTICES.md`.

## Current architecture

```text
Sources
  -> Collectors
  -> CollectorResult / Source Health
  -> Normalize
  -> In-batch deduplicate
  -> Seen / Pushed state
  -> Deterministic ranking
  -> Source-balanced candidate pool
  -> Shortlist
  -> Shortlist enrichment
  -> Optional OpenAI-compatible LLM analysis
  -> Final source-balanced Top 5-10
  -> Markdown digest
  -> Telegram publisher
  -> State persist
```

## Implemented in this round

- Correct independent Git checkout was created and used.
- Source health model added: `CollectorResult`, `RunStats`.
- Collector failures no longer create fake `RadarItem` candidates.
- RSS collector now returns health results.
- arXiv collector now returns health results and categories.
- GitHub collector now supports dynamic lookback-based `pushed:>{since}` queries.
- GitHub raw metadata now includes stars, forks, topics, language, created_at, pushed_at.
- Anthropic sitemap collector added.
- HuggingFace Papers API collector added, replacing the unauthorized RSS endpoint.
- Hacker News collector added via Algolia API, avoiding slow topstories N+1 fetching.
- Shortlist enrichment added for blog pages and GitHub repositories.
- GitHub enrichment skips locally when no `GITHUB_TOKEN` is present; GitHub Actions provides `${{ github.token }}`.
- Deterministic ranking expanded with project transferability, old popular GitHub repo penalty, hype penalty, and configurable weights.
- Source-balanced selection added before expensive shortlist work and before final output.
- LLM analyzer upgraded to structured JSON with relevance, engineering value, novelty, actionability, project transferability, explanations, and experiment idea.
- LLM defaults target Agnes OpenAI-compatible endpoint but secrets are never stored.
- CLI added: `python -m radar.main --config config/radar.json --check-llm`.
- Digest now includes Run Stats / Source Health, `今天只看一条`, and `今天最值得动手的一条`.
- Telegram publisher keeps automatic splitting, compact mobile-friendly output, retry, and HTTP status checks.
- GitHub Actions updated with `workflow_dispatch`, daily schedule, concurrency, tests, optional LLM check, run, artifact upload, state/report persistence, and `${{ github.token }}`.
- Tests expanded from 6 to 16 meaningful tests.

## Verified commands

From `research-engineer-radar-remote/`, because an older editable install pointed imports to the old untracked directory, tests were run with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Result:

```text
Ran 16 tests in 0.040s
OK
```

Dry-run:

```bash
PYTHONPATH=src python -m radar.main --config config/radar.json --dry-run
```

Latest verified result:

```text
collected=131
deduplicated=130
eligible=80
shortlist=16
final_items=8
```

All configured collectors completed OK in the latest dry-run:

- OpenAI: 10
- Netflix Tech Blog: 10
- Cloudflare: 10
- Simon Willison: 10
- Lilian Weng: 10
- Anthropic sitemap: 8
- HuggingFace Papers: 10
- GitHub Search: 33 across five queries
- arXiv: 22 across three queries
- Hacker News: 8

## Known limitations / not completed yet

- `LLM_API_KEY` is not configured locally, so Agnes models/chat tests were skipped. The pipeline correctly falls back to deterministic ranking.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are not configured locally, so no real Telegram message was sent in this environment.
- GitHub Actions manual trigger was not run from this local environment.
- The old untracked local directory still exists at `research-engineer-radar/`; do not accidentally work there unless intentionally comparing old local work.

## Required GitHub Secrets / Variables

Secrets:

```text
LLM_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
SEMANTIC_SCHOLAR_KEY  # optional, reserved for Phase 2
```

Variables:

```text
LLM_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.5-flash
```

GitHub token:

Use `${{ github.token }}`. Do not create a separate PAT unless a future workflow truly needs it.

## Next steps

1. Configure GitHub Secrets for Telegram and Agnes.
2. Run `--check-llm` in Actions or locally after secrets are present.
3. Send a small Telegram test before the first full production push.
4. Run manual `workflow_dispatch` once and verify state/report commit succeeds.
5. Watch the first week of reports and tune weights/profile based on whether the final Top 5-10 are worth reading.
6. Phase 2: add Semantic Scholar/Crossref/Papers with Code only after v1 report quality is stable.
