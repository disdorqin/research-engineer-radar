# Architecture

Research Engineer Radar v0.1 使用一条可解释的轻量 pipeline：

```text
Sources
  ↓
Collectors
  ↓
Normalize
  ↓
Deduplicate
  ↓
Cheap deterministic ranking
  ↓
Shortlist
  ↓
Optional LLM analysis
  ↓
Final ranking
  ↓
Digest
  ↓
Publisher: Telegram / WeCom
  ↓
State: data/seen.json
```

## 为什么先确定性 ranking

不要把所有候选直接送进 LLM。先用 metadata、keyword、source priority、freshness、hype penalty 做便宜筛选，再让 LLM 只处理 shortlist。

这样可以降低：API 成本、运行延迟、随机性和不可解释性。

## 为什么不引入数据库

第一版只需要 `data/seen.json`。状态记录 URL / 内容 ID / 首次发现时间 / 来源 / 是否推送即可。数据库、向量库和复杂基础设施会把问题从“筛出高价值内容”转移成“维护系统”。

## 为什么 Publisher 可插拔

当前首选 Telegram，WeCom 作为第二通道。飞书暂时不用。Publisher 的实现和 pipeline 解耦，后续可以加邮件、Slack 或网页 Dashboard。
