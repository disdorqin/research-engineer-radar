# Research Engineer Radar

Research Engineer Radar 是面向 **AI Research Engineer / AI 科研工程师** 成长方向的每日情报雷达。

它不是 Hot 100 新闻聚合器，也不是“抓得越多越好”的新闻机器人。核心目标是：从大量候选中筛出每天真正值得投入时间的 5-10 条内容，并说明它为什么值得看、对能力树有什么帮助、对当前项目有什么迁移价值，以及下一步应该精读、浏览、收藏还是动手实验。

## 当前 pipeline

```text
Sources
  ↓
Collectors
  ↓
CollectorResult / Source Health
  ↓
Normalize + in-batch deduplicate
  ↓
State (seen != pushed)
  ↓
Deterministic ranking
  ↓
Source-balanced candidate pool
  ↓
Shortlist enrichment
  ↓
Optional LLM personal analysis
  ↓
Final ranking + final source balance
  ↓
Top 5-10 digest
  ↓
Telegram
  ↓
State + report persist
```

## 当前能力

- RSS / Atom：OpenAI、Netflix Tech Blog、Cloudflare、Simon Willison、Lilian Weng。
- Sitemap：Anthropic 官方站点。
- GitHub Search：动态 `lookback_days` 生成 `pushed:>{since}`，不写死日期。
- arXiv：ML systems、serving、time-series、concept drift 等查询。
- HuggingFace Papers：使用公开 API，替代会 401 的 RSS。
- Hacker News：通过 Algolia 低成本抓社区信号，避免官方 topstories N+1 慢抓。
- Source Health：Collector 失败进入运行统计，不生成假候选。
- Ranking：topic alignment、engineering value、source quality、freshness、actionability、project transferability、GitHub signal、hype penalty、old popular repo penalty。
- Shortlist enrichment：只 enrich shortlist，不对所有候选抓全文。
- LLM：OpenAI-compatible，默认面向 Agnes；无 key 时确定性 fallback。
- Telegram：自动分块、压缩手机版摘要、重试、HTTP 状态检查。
- GitHub Actions：workflow_dispatch + 每天 08:30 Asia/Shanghai 定时运行。

## 运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m radar.main --config config/radar.json --dry-run
```

如果本机曾经安装过旧的 editable 包，建议测试时显式指定：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m radar.main --config config/radar.json --dry-run
```

## LLM 检查

```bash
PYTHONPATH=src python -m radar.main --config config/radar.json --check-llm
```

需要环境变量：

```text
LLM_API_KEY
LLM_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.5-flash
```

## GitHub Secrets / Variables

Secrets：

```text
LLM_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
SEMANTIC_SCHOLAR_KEY  # optional, reserved
```

Variables：

```text
LLM_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.5-flash
```

GitHub API 使用 Actions 自带的 `${{ github.token }}`，不需要额外 PAT。

## Telegram Bot 设置

1. 在 Telegram 找 `@BotFather`。
2. `/newbot` 创建 Bot。
3. 复制 Bot Token 到 GitHub Secret：`TELEGRAM_BOT_TOKEN`。
4. 给 Bot 发一条消息，或把 Bot 拉进目标群。
5. 获取 chat id 后配置 GitHub Secret：`TELEGRAM_CHAT_ID`。
6. 先运行小测试，再开启完整日报。

不要把真实 Token 写进源码、配置、日志或聊天。

## 文档

- `docs/ARCHITECTURE.md`：架构说明。
- `docs/GAP_ANALYSIS.md`：差距分析。
- `docs/PROJECT_MEMORY.md`：跨对话开发记忆。
- `THIRD_PARTY_NOTICES.md`：参考项目与 License 记录。

## 项目边界

第一阶段不做 PostgreSQL、Vector DB、Kubernetes、多 Agent、RAG、Web App、移动 App。所有工作先服务于一个指标：

> 每天最后留下来的 5-10 条，我是否真的愿意花时间看。
