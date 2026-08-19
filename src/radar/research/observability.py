from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class TraceEvent:
    stage: str
    detail: str
    elapsed_ms: int


@dataclass(slots=True)
class ResearchTrace:
    trace_id: str
    query: str
    started_at: str
    provider_counts: dict[str, int] = field(default_factory=dict)
    events: list[TraceEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nodes: int = 0
    edges: int = 0
    crawl_fetches: int = 0
    duration_ms: int = 0
    _started_perf: float = field(default_factory=time.perf_counter, repr=False)

    @classmethod
    def start(cls, query: str) -> "ResearchTrace":
        return cls(
            trace_id=uuid.uuid4().hex[:12],
            query=query,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def event(self, stage: str, detail: str) -> None:
        elapsed = int((time.perf_counter() - self._started_perf) * 1000)
        self.events.append(TraceEvent(stage=stage, detail=detail, elapsed_ms=elapsed))

    def provider(self, name: str, count: int) -> None:
        self.provider_counts[name] = self.provider_counts.get(name, 0) + int(count)

    def finish(self, nodes: int, edges: int, crawl_fetches: int, warnings: list[str]) -> None:
        self.nodes = nodes
        self.edges = edges
        self.crawl_fetches = crawl_fetches
        self.warnings = list(warnings)
        self.duration_ms = int((time.perf_counter() - self._started_perf) * 1000)
        self.event("finish", f"nodes={nodes} edges={edges} fetches={crawl_fetches}")

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("_started_perf", None)
        return payload


def append_trace(path: str | Path | None, trace: ResearchTrace) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace.to_dict(), ensure_ascii=False) + "\n")
