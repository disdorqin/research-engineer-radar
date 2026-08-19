# Research Engineer Radar

Research Engineer Radar 是面向 **AI Research Engineer / AI 科研工程师** 成长方向的每日情报雷达。

它不是 Hot 100 新闻聚合器，也不是“抓得越多越好”的新闻机器人。v0.4 的核心问题是：

> 实验室和企业是怎样把 AI 系统从“能做出来”，推进到“能稳定运行、能评测、能优化、能落地”的？

当前优先学习四条主线：

- **Agent Engineering（30%）**：架构、tool use、context/memory、evaluation、observability、reliability、checkpoint/recovery、production engineering。
- **Engineering Methodology（25%）**：性能瓶颈定位、实验设计、benchmark、可观测性、故障分析、成本/延迟优化、trade-off。
- **Performance / AI Systems（25%）**：Python 性能、GPU utilization、batching、caching、I/O、memory、serving、latency、throughput。
- **Frontier Research & Tools（20%）**：OpenAI / Anthropic / Google 的 Agent 工程、AI Infra、新型时序预测方法。

这些是软权重，不是硬配额；质量优先。

## v0.4 的判断原则

- 方法论优先于单一项目经验。
- 当前数学建模 Agent、电力预测等项目只作为**可选现实案例**，没有直接关系就不写，禁止为了“个性化”强行建立联系。
- 性能内容优先寻找“**测量 → 定位 → 假设 → 优化 → 验证**”闭环。
- Agent 内容优先寻找从 Demo 到可靠系统之间的工程差距：evaluation、trace、failure mode、retry/fallback、checkpoint、state、security、cost、deployment。
- Demo-only、营销、浅教程、只有发布没有评测/生产信号的内容降权。

## 当前 pipeline

```text
Sources
  ↓
Collectors + Source Health
  ↓
Normalize + Deduplicate
  ↓
Methodology-first deterministic ranking
  ↓
Source-balanced candidate pool
  ↓
Shortlist enrichment
  ↓
LLM technical-editor analysis
  ↓
Final ranking
  ├── Telegram Lite Digest (3-5 条，人读)
  └── Full Markdown Report (Top 8 + debug / scores / source health)
  ↓
State persist
```

## Telegram 与完整报告分层

Telegram 不再发送 Run Stats、排序信号和大段报告，只保留：

- ⭐ 今天最值得看
- 它真正解决的问题
- 真正值得学的方法 / 设计思想
- 以后什么时候应该想起它
- Agent / 性能专项启发（适用时）
- 🛠 今天可以动手
- 👀 另外几条值得知道

完整的 Top Radar、Source Health、Deterministic signals、LLM 价值评分仍保存在 GitHub Artifact / `reports/*.md`，用于深入阅读与调试。

## 当前能力

- RSS / Atom：OpenAI、Netflix Tech Blog、Cloudflare、Simon Willison、Lilian Weng。
- Sitemap：Anthropic 官方站点。
- GitHub Search：Agent reliability/evaluation、Agent framework/tool calling、inference/GPU/batching/cache、profiling/benchmark、time-series。
- arXiv：Agent evaluation/reliability、ML systems/inference、time-series/concept drift/online learning。
- HuggingFace Papers、Hacker News。
- Source Health：单个 Collector 失败不会拖垮整条 pipeline。
- LLM：OpenAI-compatible，默认 Agnes；支持分析失败重试与 deterministic fallback。
- Telegram：自动分块、重试、HTTP 状态检查。
- GitHub Actions：workflow_dispatch + 每天 08:30 Asia/Shanghai 定时运行。

## 本地运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m radar.main --config config/radar.json --dry-run
```

测试：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m radar.main --config config/radar.json --dry-run
```

LLM 连通性检查：

```bash
PYTHONPATH=src python -m radar.main --config config/radar.json --check-llm
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

GitHub API 使用 Actions 自带的 `${{ github.token }}`，不需要额外 PAT。不要把真实 Token 写进源码、配置、日志或聊天。

## 项目边界

当前不急着增加数据库、Vector DB、RAG、Multi-Agent、Dashboard 或更多信息源。

当前唯一 KPI：

> 每天 Telegram 里是否至少有 1-2 条内容，让人觉得“这东西确实让我学会了一个以后还能复用的判断或工程方法”。
