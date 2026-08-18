from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from radar.collectors import collect_arxiv, collect_github, collect_rss
from radar.config import load_config
from radar.digest.markdown import render_digest
from radar.publishers.telegram import publish_telegram
from radar.publishers.wecom import publish_wecom
from radar.ranking.scorer import rank_items
from radar.state.seen import SeenState


def run(config_path: str, dry_run: bool = False) -> Path:
    cfg = load_config(config_path)
    data = cfg.data

    candidates = []
    candidates.extend(collect_rss(data.get("rss_sources", [])))
    candidates.extend(collect_github(data.get("github_queries", [])))
    candidates.extend(collect_arxiv(data.get("arxiv_queries", [])))
    candidates = candidates[: cfg.max_candidates]

    state = SeenState(cfg.state_path)
    fresh_candidates = state.filter_new(candidates)

    shortlist = rank_items(fresh_candidates, data, limit=cfg.shortlist_size)
    final_items = shortlist[: cfg.top_n]

    digest = render_digest(final_items, datetime.now())
    cfg.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = cfg.report_dir / f"radar-{datetime.now().strftime('%Y%m%d')}.md"
    report_path.write_text(digest, encoding="utf-8")

    if not dry_run:
        publishers = data.get("publishers", {})
        if publishers.get("telegram", {}).get("enabled", False):
            publish_telegram(digest)
        if publishers.get("wecom", {}).get("enabled", False):
            publish_wecom(digest)
        state.mark_pushed([ranked.item for ranked in final_items])
        state.save()

    return report_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Research Engineer Radar")
    parser.add_argument("--config", default="config/radar.json")
    parser.add_argument("--dry-run", action="store_true", help="Generate report without sending publishers or updating seen state")
    args = parser.parse_args(argv)
    report = run(args.config, dry_run=args.dry_run)
    print(f"Report written: {report}")


if __name__ == "__main__":
    main()
