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
    # v0.4: score reusable engineering/research judgment, not forced project relevance.
    long_term_value: float = 0.0
    methodology_value: float = 0.0
    engineering_depth: float = 0.0
    production_value: float = 0.0
    transferability: float = 0.0
    novelty: float = 0.0
    actionability: float = 0.0

    category: str = ""
    core_problem: str = ""
    key_takeaway: str = ""
    design_tradeoff: str = ""
    maturity_signal: str = ""
    when_to_recall: str = ""
    agent_insight: str = ""
    performance_insight: str = ""
    current_project_relation: str = ""
    suggested_action: str = "浏览"
    experiment_idea: str = ""

    @property
    def score(self) -> float:
        weighted = (
            self.long_term_value * 0.18
            + self.methodology_value * 0.20
            + self.engineering_depth * 0.18
            + self.production_value * 0.15
            + self.transferability * 0.15
            + self.novelty * 0.07
            + self.actionability * 0.07
        )
        return max(0.0, min(weighted, 1.0))

    # Backward-compatible aliases for older report/tests and external callers.
    @property
    def relevance(self) -> float:
        return self.long_term_value

    @property
    def engineering_value(self) -> float:
        return self.engineering_depth

    @property
    def project_transferability(self) -> float:
        return self.transferability

    @property
    def what_it_is(self) -> str:
        return self.core_problem

    @property
    def why_it_matters(self) -> str:
        return self.key_takeaway

    @property
    def ability_tree_relation(self) -> str:
        return self.when_to_recall

    @property
    def what(self) -> str:
        return self.core_problem

    @property
    def why(self) -> str:
        return self.key_takeaway

    @property
    def capability_relation(self) -> str:
        return self.when_to_recall

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
