# Research Navigator V1.0 Setup Checklist

这份文档用于把 Telegram Research Navigator 从“能聊天的过渡版”配置成更完整的主动检索助手。

## 1. 当前最小可用配置

必须有这些 GitHub Secrets：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `LLM_API_KEY`

可选 GitHub Variables：

- `LLM_BASE_URL`，默认 `https://apihub.agnes-ai.com/v1`
- `LLM_MODEL`，默认 `agnes-2.5-flash`

## 2. 可选增强：X / Twitter Recent Search

Research Navigator 会读取：

- GitHub Secret: `X_BEARER_TOKEN`

获取方式：

1. 打开 X Developer Portal。
2. 创建 Project / App。
3. 进入 App 的 `Keys and tokens`。
4. 复制 App 的 Bearer Token。
5. 在 GitHub 仓库中进入 `Settings → Secrets and variables → Actions → New repository secret`。
6. Name 填 `X_BEARER_TOKEN`，Value 粘贴 Bearer Token。
7. 保存后重新运行 `Telegram Research Navigator` workflow。

没有这个 Secret 时，系统会自动退化到 `site:x.com ...` 的 Web Search fallback，不会阻断主流程。

## 3. 可选增强：YouTube Data API

Research Navigator 会读取：

- GitHub Secret: `YOUTUBE_API_KEY`

获取方式：

1. 打开 Google Cloud Console。
2. 创建或选择一个项目。
3. 启用 `YouTube Data API v3`。
4. 创建 API Key。
5. 在 GitHub 仓库中进入 `Settings → Secrets and variables → Actions → New repository secret`。
6. Name 填 `YOUTUBE_API_KEY`，Value 粘贴 API Key。
7. 保存后重新运行 workflow。

没有这个 Secret 时，系统会自动退化到 `site:youtube.com ...` 的 Web Search fallback。

## 4. 可选增强：SearXNG

Research Navigator 会读取：

- GitHub Variable: `SEARXNG_BASE_URL`

如果你部署了自己的 SearXNG 实例，把它的 base URL 填入该 Variable。系统会优先使用 SearXNG；如果不可用，会 fallback 到 DuckDuckGo HTML Search。

## 5. 运行与测试

手动运行：

`Actions → Telegram Research Navigator → Run workflow → main`

或者等待每 30 分钟的过渡版 long polling。

在 Telegram 里测试：

```text
最近一个月 Agent Skills 为什么突然这么多人讨论？优先找一手来源，帮我把官方文章、论文、代码和作者讨论串成来源链，不要浅教程。
```

继续追问：

```text
深挖第2条
把它追到最原始来源
/trace
/status
```

本地/CI 回归测试：

```bash
python -m unittest discover -s tests -v
python -m radar.eval.benchmark
```

## 6. 隐私说明

`data/telegram_sessions.json` 是运行时会话状态，包含 Chat ID、上一轮 query 与部分搜索结果。它现在被 `.gitignore` 忽略，不应该提交到公开仓库。

GitHub Actions 过渡版不再把 Telegram session 自动 commit 回仓库。这样更安全，但跨窗口连续上下文可能不如常驻 webhook 稳定。生产版建议使用 `radar-webhook` + 持久化数据库/磁盘卷。
