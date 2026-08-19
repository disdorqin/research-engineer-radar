# Third-party reference notes

This project does not vendor third-party repositories.

The following repositories were cloned into a sibling reference directory outside this Git repository and were used for architectural comparison / implementation ideas only:

- `OvOhao/auto-paper-collecter` — MIT License. Ideas reviewed: multi-source paper radar, OpenAI-compatible API configuration, Crossref / Semantic Scholar / HuggingFace / Papers with Code source design, feedback data shape, Telegram push.
- `duanyytop/agents-radar` — MIT License. Ideas reviewed: source health, GitHub / HN / Product Hunt / official-site discovery, sitemap-based official-source monitoring, GitHub Actions persistence.
- `backpropagation6/ai-news-scanner` — MIT License. Ideas reviewed: config-driven sources, professional profile, relevance scoring, Telegram notification, test organization.
- `AutoLLM/ArxivDigest` — MIT License. Ideas reviewed: natural-language user profile and LLM relevance rating for papers.

No substantial third-party code was copied into this repository. The current implementation is a small stdlib-based implementation adapted to this project's interfaces and requirements.
