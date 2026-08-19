from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from radar.models import RankedItem, RunStats


def _short(value: str, limit: int = 520) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _https(url: str) -> str:
    return "https://" + url[7:] if url.startswith("http://") else url


def _local_time(generated_at: datetime, timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=zone)
        else:
            generated_at = generated_at.astimezone(zone)
        return generated_at.strftime("%Y-%m-%d %H:%M") + f"（{timezone_name}）"
    except Exception:
        return generated_at.isoformat(timespec="minutes")


def _component_line(row: RankedItem) -> str:
    return ", ".join(f"{key}={value:.2f}" for key, value in row.component_scores.items())


def _core_problem(row: RankedItem) -> str:
    if row.llm and row.llm.core_problem:
        return row.llm.core_problem
    return _short(row.item.summary, 360) or "需要打开原文进一步确认其核心问题。"


def _takeaway(row: RankedItem) -> str:
    if row.llm and row.llm.key_takeaway:
        return row.llm.key_takeaway
    return "; ".join(row.reasons[:4]) if row.reasons else "暂未提炼出足够明确的可迁移方法。"


def _when(row: RankedItem) -> str:
    if row.llm and row.llm.when_to_recall:
        return row.llm.when_to_recall
    return "当你遇到类似的系统设计、性能、评测或研究工程问题时，再回来看它。"


def _category(row: RankedItem) -> str:
    if row.llm and row.llm.category:
        return row.llm.category
    text = row.item.text_for_scoring()
    if "agent" in text:
        return "Agent Engineering"
    if any(term in text for term in ["profil", "gpu", "latency", "throughput", "cache", "batch"]):
        return "性能工程"
    if any(term in text for term in ["time series", "forecast"]):
        return "时序预测"
    return "前沿技术"


def _pick_do_item(items: list[RankedItem]) -> RankedItem | None:
    candidates = [
        row for row in items
        if row.action == "尝试" or (row.llm and row.llm.experiment_idea) or row.component_scores.get("actionability", 0) >= 0.5
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (row.llm.actionability if row.llm else row.component_scores.get("actionability", 0), row.score))


def render_telegram_digest(
    items: list[RankedItem],
    generated_at: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    max_items: int = 5,
) -> str:
    generated_at = generated_at or datetime.now()
    visible = [row for row in items if row.action != "跳过"][:max_items]
    lines = [
        "🔥 Research Engineer Radar",
        f"{_local_time(generated_at, timezone_name)}",
        "",
    ]
    if not visible:
        lines.append("今天没有值得占用你注意力的新内容。")
        return "\n".join(lines).strip() + "\n"

    top = visible[0]
    lines.extend([
        "⭐ 今天最值得看",
        f"《{top.item.title}》",
        "",
        f"它在解决：{_short(_core_problem(top), 260)}",
        f"真正值得学：{_short(_takeaway(top), 360)}",
        f"以后什么时候想起它：{_short(_when(top), 260)}",
    ])
    if top.llm and top.llm.agent_insight:
        lines.append(f"🤖 Agent 启发：{_short(top.llm.agent_insight, 300)}")
    if top.llm and top.llm.performance_insight:
        lines.append(f"⚙️ 性能启发：{_short(top.llm.performance_insight, 300)}")
    lines.extend([f"👉 {top.action} · {_https(top.item.url)}", ""])

    do_item = _pick_do_item(visible[1:])
    if do_item:
        idea = do_item.llm.experiment_idea if do_item.llm else ""
        lines.extend([
            "🛠 今天可以动手",
            f"《{do_item.item.title}》",
            _short(idea or _takeaway(do_item), 300),
            f"👉 {do_item.action} · {_https(do_item.item.url)}",
            "",
        ])

    others = [row for row in visible[1:] if row is not do_item]
    if others:
        lines.extend(["👀 另外几条值得知道", ""])
        for row in others:
            lines.extend([
                f"【{_category(row)}】{row.item.title}",
                _short(_takeaway(row), 210),
                f"{row.action} · {_https(row.item.url)}",
                "",
            ])

    lines.append("完整技术报告与评分已保存在 GitHub Artifact。")
    return "\n".join(lines).strip() + "\n"


def render_digest(
    items: list[RankedItem],
    generated_at: datetime | None = None,
    stats: RunStats | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    generated_at = generated_at or datetime.now()
    lines = [
        "# Research Engineer Radar — Full Report",
        "",
        f"生成时间：{_local_time(generated_at, timezone_name)}",
        "",
        "> 完整报告用于复盘、调试与深入阅读；Telegram 只发送移动端精简版。",
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

    lines.extend(["## Top Radar", ""])
    for idx, row in enumerate(items, start=1):
        item = row.item
        analysis = row.llm
        lines.extend([
            f"### {idx}. {item.title}",
            "",
            f"- 分类：{_category(row)}",
            f"- 来源：{item.source}",
            f"- 发布时间：{item.published_at.isoformat(timespec='seconds') if item.published_at else '未知'}",
            f"- 链接：{_https(item.url)}",
            f"- 最终分数：{row.score:.3f}",
            f"- 建议动作：{row.action}",
            "",
            f"**核心问题**：{_short(_core_problem(row))}",
            "",
            f"**真正值得学**：{_short(_takeaway(row))}",
            "",
            f"**以后什么时候想起它**：{_short(_when(row))}",
            "",
        ])
        if analysis:
            if analysis.design_tradeoff:
                lines.extend([f"**关键 Trade-off**：{_short(analysis.design_tradeoff)}", ""])
            if analysis.maturity_signal:
                lines.extend([f"**成熟系统信号**：{_short(analysis.maturity_signal)}", ""])
            if analysis.agent_insight:
                lines.extend([f"**Agent 启发**：{_short(analysis.agent_insight)}", ""])
            if analysis.performance_insight:
                lines.extend([f"**性能启发**：{_short(analysis.performance_insight)}", ""])
            if analysis.current_project_relation and analysis.current_project_relation != "无明显直接关联":
                lines.extend([f"**当前工作可选关联**：{_short(analysis.current_project_relation)}", ""])
            if analysis.experiment_idea:
                lines.extend([f"**最小实验**：{_short(analysis.experiment_idea)}", ""])
            lines.extend([
                "**LLM 价值评分**："
                f"long_term={analysis.long_term_value:.2f}, methodology={analysis.methodology_value:.2f}, "
                f"engineering_depth={analysis.engineering_depth:.2f}, production={analysis.production_value:.2f}, "
                f"transferability={analysis.transferability:.2f}, novelty={analysis.novelty:.2f}, actionability={analysis.actionability:.2f}",
                "",
            ])
        lines.extend([
            f"**Deterministic signals**：{_component_line(row)}",
            f"**Reasons**：{'; '.join(row.reasons[:8]) if row.reasons else '无'}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"
