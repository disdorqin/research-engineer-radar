from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class RadarItem:
    title: str
    url: str
    source: str
    summary: str = ""
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def text_for_scoring(self) -> str:
        return " ".join([self.title, self.summary, " ".join(self.tags)]).lower()


@dataclass(slots=True)
class RankedItem:
    item: RadarItem
    score: float
    reasons: list[str] = field(default_factory=list)
    action: str = "浏览"
    llm_note: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
