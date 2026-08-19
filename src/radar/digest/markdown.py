from __future__ import annotations

from datetime import datetime

from radar.models import RankedItem, RunStats


def _short(value: str, limit: int = 520) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _component_line(row: RankedItem) -> str:
    return ", ".join(f"{key}={value:.2f}" for key, value in row.component_scores.items())


def _what(row: RankedItem) -> str:
    return row.llm.what_it_is if row.llm and row.llm.what_it_is else _short(row.item.summary, 360) or "一个需要进一步打开查看的候选。"


def _why(row: RankedItem) -> str:
    if row.llm and row.llm.why_it_matters:
        return row.llm.why_it_matters
    return "; ".join(row.reasons[:5]) if row.reasons else "暂无明确理由。"


def _ability(row: RankedItem) -> str:
    if row.llm and row.llm.ability_tree_relation:
        return row.llm.ability_tree_relation
    return "与 AI Research Engineer 的系统、工程判断、评测、MLOps 或科研迁移能力相关。"


def _project(row: RankedItem) -> str:
    if row.llm and row.llm.current_project_relation:
        return row.llm.current_project_relation
    text = row.item.text_for_scoring()
    if any(term in text for term in ["time series", "forecast", "electricity", "concept drift", "evaluation", "pipeline"]):
        return "可能迁移到当前时序/电力预测项目，尤其是评测、数据流水线、模型融合或概念漂移判断。"
    return "与当前电力预测项目弱相关，但可能对工程能力树有帮助。"


def _experiment(row: RankedItem) -> str:
    if row.llm and row.llm.experiment_idea:
        return row.llm.experiment_idea
    if row.action == "尝试" and row.component_scores.get("actionability", 0) >= 0.5:
        return "打开原文或仓库，抽取一个最小可复现实验：安装、运行示例、记录输入/输出/耗时，再判断是否值得迁移。"
    return ""


def _pick_do_item(items: list[RankedItem]) -> RankedItem | None:
    actionable = [row for row in items if row.action == "尝试" or row.component_scores.get("actionability", 0) >= 0.5]
    if actionable:
        return max(actionable, key=lambda row: row.score)
    return items[0] if items else None


def render_digest(items: list[RankedItem], generated_at: datetime | None = None, stats: RunStats | None = None) -> str:
    generated_at = generated_at or datetime.now()
    lines = [
        "# 🔥 Research Engineer Radar Daily",
        "",
        f"生成时间：{generated_at.isoformat(timespec='seconds')}",
        "",
        "今天目标不是抓更多，而是留下更值得看的少量内容，并说明它为什么值得投入时间。",
        "",
    ]

    if stats:
        lines.extend([
            "## Run Stats / Source Health",
            "",
            f"- collected: {stats.collected_count}",
            f"- deduplicated: {stats.deduplicated_count}",
            f"- eligible: {stats.eligible_count}",
            f"- shortlist: {stats.shortlist_count}",
            f"- final: {stats.final_count}",
            f"- llm: {'enabled' if stats.llm_enabled else 'disabled/fallback'}; used={stats.llm_used_count}; failed={stats.llm_failed_count}",
            "",
            *stats.health_lines(),
            "",
        ])

    if items:
        lines.extend([
            "## 🔥 今天只看一条",
            "",
            f"**{items[0].item.title}**",
            "",
            f"链接：{items[0].item.url}",
            "",
        ])
        do_item = _pick_do_item(items)
        if do_item:
            lines.extend([
                "## 🛠 今天最值得动手的一条",
                "",
                f"**{do_item.item.title}**",
                "",
                f"建议动作：{do_item.action}",
                "",
            ])
    else:
        lines.extend(["## 🔥 今天只看一条", "", "今天没有新的高价值候选。", ""])

    lines.extend(["## Top Radar", ""])
    for idx, row in enumerate(items, start=1):
        item = row.item
        experiment = _experiment(row)
        lines.extend([
            f"### {idx}. {item.title}",
            "",
            f"- 来源：{item.source}",
            f"- 发布时间：{item.published_at.isoformat(timespec='seconds') if item.published_at else '未知'}",
            f"- 链接：{item.url}",
            f"- 最终分数：{row.score:.3f}",
            f"- 建议动作：{row.action}",
            "",
            f"**这是什么**：{_short(_what(row))}",
            "",
            f"**为什么值得看**：{_short(_why(row))}",
            "",
            f"**关键工程点**：{'; '.join(row.reasons[:6]) if row.reasons else '待打开原文确认'}",
            "",
            f"**和 AI Research Engineer 能力树的关系**：{_short(_ability(row))}",
            "",
            f"**和当前项目的关系**：{_short(_project(row))}",
            "",
        ])
        if experiment:
            lines.extend([f"**最小实验**：{_short(experiment)}", ""])
        lines.extend([f"排序信号：{_component_line(row)}", ""])
    return "\n".join(lines).strip() + "\n"
