# Research Engineer Radar

Research Engineer Radar 是一个面向 **AI Research Engineer / AI 科研工程师** 成长方向的每日情报机器人。它不是 Hot 100 新闻聚合器，也不是简单论文推送，而是把少量高价值工程与科研信息筛出来，帮助使用者逐步形成技术判断力。

核心目标：

> 降低高价值工程与科研信息的发现成本，让每天真正值得看的内容变少、变准、变可行动。

## v0.1 范围

- 多来源采集：RSS/Atom、GitHub Search、arXiv Atom API。
- 标准化与去重：统一为 `RadarItem`，用 URL / 标题 hash 记录 `data/seen.json`。
- 便宜的确定性排序：先用 metadata、关键词、来源优先级、topic 权重、hype penalty 做粗排。
- shortlist 后再可选 LLM 分析：只把少量候选交给 LLM，降低成本、延迟和随机性。
- Digest 输出：Markdown 日报，Top 5-10，包含“这是什么 / 为什么值得看 / 关系 / 建议动作”。
- Publisher 可插拔：Telegram 首选，WeCom 预留。
- GitHub Actions：支持 `workflow_dispatch` 和 Asia/Shanghai 每日定时运行。

不做：数据库、向量库、Kubernetes、多 Agent 大系统、一次抓 100 条然后全丢给 LLM。

## 目录结构

```text
src/radar/
├── collectors/      # RSS/Atom、GitHub、arXiv
├── processing/      # URL 规范化、去重辅助
├── ranking/         # 确定性 ranking
├── digest/          # Markdown digest
├── publishers/      # Telegram / WeCom
├── state/           # seen.json 状态
└── main.py          # pipeline 编排
```

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
python -m radar.main --config config/radar.json --dry-run
```

## 测试

```bash
python -m unittest discover -s tests -v
```

## GitHub Secrets

不要把真实 Token 写进代码、`.env` 或聊天。仓库需要配置：

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
LLM_API_KEY          # 可选
WECOM_WEBHOOK_URL   # 可选
```

可选 Variables：

```text
LLM_BASE_URL
LLM_MODEL
```

## 设计原则

这个系统真正优化的不是每天抓多少新闻，而是每天让使用者以更低成本接触少量真正值得看的工程和科研信息，并逐渐形成自己的判断力。
