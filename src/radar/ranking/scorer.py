from __future__ import annotations

from datetime import datetime, timezone

from radar.models import RadarItem, RankedItem


def _freshness_score(item: RadarItem) -> float:
    if item.published_at is None:
        return 0.10
    now = datetime.now(timezone.utc)
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    days = max((now - published).days, 0)
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.7
    if days <= 120:
        return 0.35
    return 0.10


def rank_items(items: list[RadarItem], config: dict, limit: int | None = None) -> list[RankedItem]:
    topic_weights = config.get("topic_weights", {})
    keywords = config.get("keywords", {})
    source_priority = config.get("source_priority", {})
    hype_terms = [term.lower() for term in config.get("hype_terms", [])]

    ranked: list[RankedItem] = []
    for item in items:
        text = item.text_for_scoring()
        score = 0.0
        reasons: list[str] = []

        for topic, weight in topic_weights.items():
            matched = [kw for kw in keywords.get(topic, []) if kw.lower() in text]
            if matched:
                topic_score = min(len(matched), 5) / 5 * float(weight)
                score += topic_score
                reasons.append(f"{topic}: " + ", ".join(matched[:3]))

        score += float(source_priority.get(item.source, 0.50)) * 0.20
        reasons.append(f"source_quality:{item.source}")
        score += _freshness_score(item) * 0.15

        stars = int(item.raw.get("stars", 0) or 0)
        if stars:
            score += min(stars / 5000, 1.0) * 0.10
            reasons.append(f"github_stars:{stars}")

        if any(term in text for term in hype_terms):
            score -= 0.12
            reasons.append("hype_penalty")
        if "collector-error" in item.tags:
            score -= 1.0

        action = "精读" if score >= 0.65 else "尝试" if score >= 0.48 else "浏览"
        ranked.append(RankedItem(item=item, score=round(score, 4), reasons=reasons, action=action))

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:limit] if limit else ranked
