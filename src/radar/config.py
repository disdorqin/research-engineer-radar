from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RadarConfig:
    data: dict[str, Any]

    @property
    def state_path(self) -> Path:
        return Path(self.data.get("state_path", "data/seen.json"))

    @property
    def report_dir(self) -> Path:
        return Path(self.data.get("report_dir", "reports"))

    @property
    def shortlist_size(self) -> int:
        return int(self.data.get("shortlist_size", 12))

    @property
    def top_n(self) -> int:
        return int(self.data.get("top_n", 8))

    @property
    def max_candidates(self) -> int:
        return int(self.data.get("max_candidates", 80))


def load_config(path: str | Path) -> RadarConfig:
    with Path(path).open("r", encoding="utf-8") as fh:
        return RadarConfig(json.load(fh))
