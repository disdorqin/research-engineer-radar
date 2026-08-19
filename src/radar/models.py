from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


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
class LLMAnalysis:
    relevance: float = 0.0
    engineering_value: float = 0.0
    novelty: float = 0.0
    actionability: float = 0.0
    project_transferability: float = 0.0
    what_it_is: str = ""
    why_it_matters: str = ""
    ability_tree_relation: str = ""
    current_project_relation: str = ""
    suggested_action: str = "浏览"
    experiment_idea: str = ""

    @property
    def score(self) -> float:
        values = [
            self.relevance,
            self.engineering_value,
            self.novelty,
            self.actionability,
            self.project_transferability,
        ]
        return max(0.0, min(sum(values) / len(values), 1.0))

    # Backward-compatible aliases used by older digest tests / reports.
    @property
    def what(self) -> str:
        return self.what_it_is

    @property
    def why(self) -> str:
        return self.why_it_matters

    @property
    def capability_relation(self) -> str:
        return self.ability_tree_relation

    @property
    def project_relation(self) -> str:
        return self.current_project_relation

    @property
    def action(self) -> str:
        return self.suggested_action


@dataclass(slots=True)
class RankedItem:
    item: RadarItem
    score: float
    reasons: list[str] = field(default_factory=list)
    action: str = "浏览"
    component_scores: dict[str, float] = field(default_factory=dict)
    llm: LLMAnalysis | None = None


CollectorStatus = Literal["OK", "FAIL", "SKIP"]


@dataclass(slots=True)
class CollectorResult:
    source: str
    items: list[RadarItem] = field(default_factory=list)
    status: CollectorStatus = "OK"
    latency_seconds: float = 0.0
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass(slots=True)
class RunStats:
    collector_results: list[CollectorResult] = field(default_factory=list)
    collected_count: int = 0
    deduplicated_count: int = 0
    eligible_count: int = 0
    shortlist_count: int = 0
    final_count: int = 0
    llm_enabled: bool = False
    llm_used_count: int = 0
    llm_failed_count: int = 0

    def add_collector(self, result: CollectorResult) -> None:
        self.collector_results.append(result)
        self.collected_count += len(result.items)

    def health_lines(self) -> list[str]:
        lines = []
        for result in self.collector_results:
            count = len(result.items)
            latency = f"{result.latency_seconds:.2f}s" if result.latency_seconds else "-"
            if result.status == "OK":
                lines.append(f"- {result.source}: OK {count} ({latency})")
            elif result.status == "SKIP":
                lines.append(f"- {result.source}: SKIP {result.error or ''}".rstrip())
            else:
                lines.append(f"- {result.source}: FAIL {result.error or 'unknown error'} ({latency})")
        return lines


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
