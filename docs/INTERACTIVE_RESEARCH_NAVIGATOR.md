# Research Navigator v0.5

The project has moved from a scheduled daily digest to an **active, conversational research navigator**.

## Product goal

The Telegram bot is now the main interface. A user should be able to write normal language such as:

- `最近 Agent evaluation 有什么真正值得看的？`
- `找最近一周 OpenAI 和 Anthropic 的 Agent 工程一手来源。`
- `Agent Skills 为什么最近突然变热？顺着来源往下找。`
- `找 GPU utilization 的工程文章，不要浅教程。`
- `深挖第 2 条。`

The user does not need to learn slash commands or search syntax.

## Runtime pipeline

```text
Telegram natural language
        ↓
Query Planner
        ↓
Topic / intent / timeframe / keywords / subqueries / platforms / depth
        ↓
Seed Search
        ├─ Web search
        ├─ arXiv
        ├─ GitHub
        ├─ Hacker News
        ├─ X discovery (web site-search fallback)
        └─ YouTube discovery (web site-search fallback)
        ↓
Source Graph
        ↓
Budgeted link traversal
        ↓
Primary-source scoring + query relevance
        ↓
Telegram result cards
        ↓
Conversation state
        ↓
“深挖第 2 条” / “只看一手” / “找作者的 X 和 YouTube”
```

## Query Planner

`src/radar/query/planner.py`

The planner does more than keyword extraction. It converts a natural-language request into a `QueryPlan`:

- normalized topic
- research intent
- time range
- expanded keywords
- several search subqueries
- platform selection
- whether primary sources are preferred
- research depth

When the configured LLM is unavailable, a deterministic fallback still produces a usable plan.

## Research graph

`src/radar/research/search.py`

Search results are not treated as independent links. Each discovered page can become a graph node and links found inside a page become provenance edges.

The current graph records:

- source URL
- target URL
- relation (`links_to`)
- discovery depth
- parent source
- source kind (paper/code/X/video/discussion/web)
- primary-source likelihood
- query score

Traversal is deliberately budgeted. The system expands only strong frontier nodes instead of crawling every link on a page.

This is the first step toward a full provenance chain such as:

```text
X discussion
    ↓
official engineering article
    ↓
arXiv paper
    ↓
GitHub repository
    ↓
author talk / later discussion
```

## Telegram conversation state

`src/radar/telegram/bot.py`

The bot stores the last topic and last result list per Chat ID. This allows follow-up requests such as `深挖第2条` to resolve the referenced result without asking the user to paste its URL again.

The session file is:

```text
data/telegram_sessions.json
```

## Current deployment

A dedicated always-on server has not been introduced yet. To make the conversational MVP usable immediately with the existing GitHub + Telegram setup, `.github/workflows/telegram-navigator.yml` runs a long-poll Telegram worker for about 27 minutes every 30 minutes.

This is a **bootstrap runtime**, not the final production architecture.

The final production target is:

```text
Telegram webhook
    ↓
small always-on Research Navigator service
    ↓
shared Query Planner / Research Graph / Ranking modules
```

Moving to a webhook service later does not require rewriting the research engine.

## Reused ideas from mature projects

The architecture intentionally borrows proven ideas instead of rebuilding everything:

- **GPT Researcher** — query decomposition, research planning, source tracking, recursive depth/breadth research.
- **STORM / Co-STORM** — perspective-guided question generation, iterative follow-up, human steering, evolving knowledge structure.
- **Open Deep Research** — configurable search backends, model separation, evaluation-first research-agent engineering.
- **MindSearch** — multi-query parallel search.
- **Crawl4AI** — target model for future deep-crawl adapter, link extraction, crash recovery and controlled traversal.
- **Firecrawl** — target hosted fallback for difficult websites and structured extraction.
- **Browser Use** — target last-resort browser fallback for JS-heavy, click-driven or authenticated pages.

The project should not fork all of these systems. It should reuse/adapt the parts that solve retrieval and browser plumbing while keeping its differentiator in three local layers:

1. Research Graph
2. Primary Source Resolver
3. Frontier / Link Planner

## Next engineering milestones

1. Replace generic web-site search fallbacks for X/YouTube with official API adapters when credentials are available.
2. Add Crawl4AI as the controllable deep-crawl engine.
3. Add a stronger Primary Source Resolver that understands author/project ownership rather than only domain heuristics.
4. Add source-chain commands and graph rendering.
5. Add benchmark tasks for primary-source recall, citation correctness, depth, duplicate rate, latency and cost.
6. Move Telegram runtime from GitHub Actions long polling to an always-on webhook service.
