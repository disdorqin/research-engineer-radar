# Research Navigator V1.0

V1.0 把项目从“每日技术雷达”正式升级为“主动式、可追溯的 Research Navigator”。

## 核心链路

Natural Language → Query Planner → Multi-source Retrieval → Canonicalization / Noise Filter → Best-first Source Graph → Provenance → Ranking → Telegram Conversation

### Query Planner

自然语言不再只提取关键词，而是生成结构化 Research Plan：topic、intent、timeframe_days、keywords、search queries、platforms、primary_only、depth、must_include、exclude_terms。

### Multi-source Retrieval

基础能力始终可用：Web Search（SearXNG 优先，DuckDuckGo fallback）、arXiv、GitHub、Hacker News。

可选官方 API：X recent search（X_BEARER_TOKEN）、YouTube Data API（YOUTUBE_API_KEY）、自建 SearXNG（SEARXNG_BASE_URL）。没有社交平台 API Key 时自动退化到 Web site-search，不阻断主流程。

### Source Graph 2.0

每个节点保存 url/source/kind/primary_score/depth/discovered_from/relation/published_at/metadata。关系不再全部叫 links_to，V1.0 会识别 cites、implements、announces、discusses、talks_about、follow_up、links_to。

Deep Search 使用 best-first frontier，而不是无脑 BFS：优先继续探索更相关、更一手、更可能带来论文/代码/作者讨论的节点，并受 max_graph_nodes / max_graph_fetches 预算控制。

### Noise Guard

统一 URL canonicalization，并过滤 GitHub Sign in / Sign up / Notifications、Privacy / Terms / Settings / Login、tracking params 和明显 UI navigation links。

### Evaluation

运行 `python -m radar.eval.benchmark`。CI 会检查时间范围解析、一手来源意图、深挖深度、用户负约束、URL canonicalization、导航噪音过滤和 provenance relation inference。

下一阶段扩展为 30–50 个真实 Research Query 的 live benchmark，重点测 Primary Source Precision@5、Source Recall、Provenance Accuracy、Noise Rate、Follow-up Consistency、Latency / Cost。

### Observability

每轮研究生成 trace：trace_id、provider_counts、nodes/edges、crawl_fetches、duration_ms、warnings、stage events。Telegram 输入 `/trace` 查看上一轮摘要；输入 `/status` 查看当前检索后端状态。

### Telegram

普通问答保持“给人看的”简洁模式，不把 Debug Report 混入结果。支持 hello/你好、深挖第2条、把第3条追到源头、只看一手来源、只看论文和代码、直接发送 URL、/status、/trace。

## Production Runtime

GitHub Actions long polling 仍保留，作为无需服务器即可运行的 transitional runtime。V1.0 同时提供 `python -m radar.telegram.webhook` 和根目录 Dockerfile，用于部署 Always-on Webhook 服务。

生产部署时配置 TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID，可选 TELEGRAM_WEBHOOK_SECRET，然后把 Telegram setWebhook 指向 `https://YOUR_HOST/telegram`。启用 webhook 后应停止 long polling。

## V1.0 定位

V1.0 不是“满分产品”，而是把最重要的工程缺口正式变成可测、可迭代的系统部件：Retrieval、Provenance、Source Graph、Evaluation、Observability、Production Runtime。后续优化以 benchmark 暴露的失败样本为主，而不是继续堆 Tool。
