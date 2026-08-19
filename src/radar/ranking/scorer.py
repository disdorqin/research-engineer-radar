from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from radar.models import RadarItem, RankedItem


def _freshness_score(item: RadarItem) -> float:
    if item.published_at is None:
        return 0.18
    now = datetime.now(timezone.utc)
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_days = max((now - published).total_seconds() / 86400, 0.0)
    if age_days <= 3:
        return 1.0
    if age_days <= 7:
        return 0.85
    if age_days <= 30:
        return 0.60
    if age_days <= 120:
        return 0.30
    return 0.08


def _term_score(text: str, terms: list[str], cap: int = 5) -> tuple[float, list[str]]:
    matched = [term for term in terms if term.lower() in text]
    return min(len(matched), cap) / cap, matched


def _github_signal(item: RadarItem) -> float:
    stars = int(item.raw.get("stars", 0) or 0)
    if not stars:
        return 0.0
    forks = int(item.raw.get("forks", 0) or 0)
    return min((stars / 8000) * 0.75 + (forks / 2000) * 0.25, 1.0)


def _old_popular_penalty(item: RadarItem) -> float:
    if item.source != "GitHub Search":
        return 0.0
    stars = int(item.raw.get("stars", 0) or 0)
    created_at = item.raw.get("created_at")
    if stars < 10000 or not created_at:
        return 0.0
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
    return 0.14 if age_days > 365 else 0.0


def rank_items(items: list[RadarItem], config: dict, limit: int | None = None) -> list[RankedItem]:
    topic_weights = config.get("topic_weights", {})
    keywords = config.get("keywords", {})
    source_priority = config.get("source_priority", {})
    hype_terms = [term.lower() for term in config.get("hype_terms", [])]
    engineering_terms = config.get("engineering_terms", [])
    action_terms = config.get("action_terms", [])
    transfer_terms = config.get("project_transfer_terms", [])
    ranking_weights = config.get("ranking_weights", {})

    weights = {
        "topic_alignment": float(ranking_weights.get("topic_alignment", 0.28)),
        "engineering_value": float(ranking_weights.get("engineering_value", 0.20)),
        "source_quality": float(ranking_weights.get("source_quality", 0.14)),
        "freshness": float(ranking_weights.get("freshness", 0.10)),
        "actionability": float(ranking_weights.get("actionability", 0.12)),
        "project_transferability": float(ranking_weights.get("project_transferability", 0.10)),
        "github_signal": float(ranking_weights.get("github_signal", 0.06)),
    }

    ranked: list[RankedItem] = []
    for item in items:
        if "collector-error" in item.tags:
            continue
        text = item.text_for_scoring()
        reasons: list[str] = []
        components: dict[str, float] = {}

        topic_alignment = 0.0
        for topic, weight in topic_weights.items():
            raw, matched = _term_score(text, keywords.get(topic, []))
            contribution = raw * float(weight)
            topic_alignment += contribution
            if matched:
                reasons.append(f"{topic}: " + ", ".join(matched[:3]))
        components["topic_alignment"] = min(topic_alignment, 1.0)

        engineering_value, engineering_matched = _term_score(text, engineering_terms, cap=4)
        components["engineering_value"] = engineering_value
        if engineering_matched:
            reasons.append("engineering: " + ", ".join(engineering_matched[:3]))

        actionability, action_matched = _term_score(text, action_terms, cap=3)
        components["actionability"] = actionability
        if action_matched:
            reasons.append("actionable: " + ", ".join(action_matched[:3]))

        transferability, transfer_matched = _term_score(text, transfer_terms, cap=4)
        components["project_transferability"] = transferability
        if transfer_matched:
            reasons.append("transfer: " + ", ".join(transfer_matched[:3]))

        source_quality = float(source_priority.get(item.source, 0.50))
        freshness = _freshness_score(item)
        github_signal = _github_signal(item)
        hype_penalty = 1.0 if any(term in text for term in hype_terms) else 0.0
        old_popular_penalty = _old_popular_penalty(item)

        components["source_quality"] = source_quality
        components["freshness"] = freshness
        components["github_signal"] = github_signal
        components["hype_penalty"] = hype_penalty
        components["old_popular_penalty"] = old_popular_penalty

        if github_signal:
            reasons.append(f"github_signal:{github_signal:.2f}")
        if hype_penalty:
            reasons.append("hype_penalty")
        if old_popular_penalty:
            reasons.append("old_popular_repo_penalty")

        score = sum(components[name] * weight for name, weight in weights.items())
        score -= hype_penalty * float(ranking_weights.get("hype_penalty", 0.12))
        score -= old_popular_penalty
        score = max(0.0, min(score, 1.0))
        action = "精读" if score >= 0.68 else "尝试" if actionability >= 0.5 and score >= 0.45 else "收藏" if score >= 0.50 else "浏览"
        ranked.append(RankedItem(item=item, score=round(score, 4), reasons=reasons, action=action, component_scores=components))

    ranked.sort(key=lambda row: row.score, reverse=True)
    return ranked[:limit] if limit else ranked


def source_balanced_select(ranked: list[RankedItem], max_items: int, config: dict) -> list[RankedItem]:
    """Soft source balancing after scoring, before expensive enrichment/LLM.

    This is not a hard quota for the final report. It only prevents an early source
    from monopolizing the shortlist candidate pool.
    """
    if max_items <= 0:
        return []
    balance_cfg = config.get("source_balance", {})
    if not balance_cfg.get("enabled", True):
        return ranked[:max_items]
    soft_quota = int(balance_cfg.get("soft_quota", 8))
    min_score_keep = float(balance_cfg.get("min_score_keep", 0.62))
    counts: dict[str, int] = defaultdict(int)
    selected: list[RankedItem] = []
    deferred: list[RankedItem] = []
    for row in ranked:
        source = row.item.source
        if counts[source] < soft_quota or row.score >= min_score_keep:
            selected.append(row)
            counts[source] += 1
        else:
            deferred.append(row)
        if len(selected) >= max_items:
            break
    if len(selected) < max_items:
        selected.extend(deferred[: max_items - len(selected)])
    selected.sort(key=lambda row: row.score, reverse=True)
    return selected[:max_items]
