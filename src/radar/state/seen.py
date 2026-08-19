from __future__ import annotations

import json
from pathlib import Path

from radar.models import RadarItem, utc_now
from radar.processing.normalize import item_id


class SeenState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                self.records = json.load(fh)
        else:
            self.records = {}

    def _id(self, item: RadarItem) -> str:
        return item_id(item.title, item.url)

    def is_seen(self, item: RadarItem) -> bool:
        return self._id(item) in self.records

    def was_pushed(self, item: RadarItem) -> bool:
        return bool(self.records.get(self._id(item), {}).get("pushed", False))

    def observe(self, items: list[RadarItem]) -> None:
        now = utc_now().isoformat()
        for item in items:
            key = self._id(item)
            record = self.records.get(key)
            if record is None:
                self.records[key] = {
                    "id": key,
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "pushed": False,
                    "pushed_at": "",
                }
            else:
                record["last_seen_at"] = now
                record["title"] = item.title
                record["url"] = item.url
                record["source"] = item.source

    def filter_new(self, items: list[RadarItem]) -> list[RadarItem]:
        return [item for item in items if not self.is_seen(item)]

    def mark_pushed(self, items: list[RadarItem]) -> None:
        self.observe(items)
        now = utc_now().isoformat()
        for item in items:
            record = self.records[self._id(item)]
            record["pushed"] = True
            record["pushed_at"] = now

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(self.records, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
