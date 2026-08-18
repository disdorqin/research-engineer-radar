from __future__ import annotations

from datetime import datetime

from radar.models import RankedItem


def render_digest(items: list[RankedItem], generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now()
    lines = [
        "# Research Engineer Radar Daily",
        "",
        f"生成时间：{generated_at.isoformat(timespec='seconds')}",
        "",
        "今天目标不是抓更多，而是留下更值得看的少量内容。",
        "",
    ]
    if items:
        lines.extend(["## 今天最值得花时间看的内容", "", f"**{items[0].item.title}**", "", f"链接：{items[0].item.url}", ""])
    else:
        lines.extend(["## 今天最值得花时间看的内容", "", "今天没有新的高价值候选。", ""])
    lines.extend(["## Top Radar", ""])
    for idx, ranked in enumerate(items, start=1):
        item = ranked.item
        reasons = "; ".join(ranked.reasons[:4]) if ranked.reasons else "暂无明确理由"
        relation = "与 AI Research Engineer 能力树相关：系统、工程判断、评测、MLOps 或科研迁移。"
        if "time series" in item.text_for_scoring() or "forecast" in item.text_for_scoring():
            relation += " 也可能迁移到当前时序/电力预测项目。"
        lines.extend([
            f"### {idx}. {item.title}",
            "",
            f"- 来源：{item.source}",
            f"- 链接：{item.url}",
            f"- 分数：{ranked.score:.3f}",
            f"- 这是什么：{item.summary[:260] or '一个需要进一步打开查看的候选。'}",
            f"- 为什么值得看：{reasons}",
            f"- 和能力树/当前项目的关系：{relation}",
            f"- 建议动作：{ranked.action}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"
