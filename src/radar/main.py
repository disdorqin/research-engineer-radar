from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from radar.ai.analyzer import analyze_shortlist, check_llm_chat, check_llm_models
from radar.collectors import collect_arxiv, collect_github, collect_hacker_news, collect_huggingface_papers, collect_rss, collect_sitemaps
from radar.config import load_config
from radar.digest.markdown import render_digest, render_telegram_digest
from radar.enrichment import enrich_shortlist
from radar.models import RunStats
from radar.processing.normalize import deduplicate_items
from radar.publishers import publish_enabled
from radar.ranking.scorer import rank_items, source_balanced_select
from radar.state.seen import SeenState


def collect_candidates(data: dict, stats: RunStats) -> list:
    collector_batches = []
    collector_batches.extend(collect_rss(data.get("rss_sources", [])))
    collector_batches.extend(collect_sitemaps(data.get("sitemap_sources", [])))
    if data.get("huggingface_papers", {}).get("enabled", False):
        collector_batches.extend(collect_huggingface_papers(data.get("huggingface_papers", {})))
    collector_batches.extend(collect_github(data.get("github_queries", []), default_lookback_days=int(data.get("github_lookback_days", 30))))
    collector_batches.extend(collect_arxiv(data.get("arxiv_queries", [])))
    if data.get("hacker_news", {}).get("enabled", False):
        collector_batches.extend(collect_hacker_news(data.get("hacker_news", {})))

    candidates = []
    for result in collector_batches:
        stats.add_collector(result)
        candidates.extend(result.items)
    deduped = deduplicate_items(candidates)
    stats.deduplicated_count = len(deduped)
    print(f"[radar] collected={len(candidates)} deduplicated={len(deduped)}")
    for line in stats.health_lines():
        print(f"[radar] health {line[2:] if line.startswith('- ') else line}")
    return deduped


def _llm_configured(data: dict) -> bool:
    cfg = data.get("llm", {})
    api_key = os.getenv(cfg.get("api_key_env", "LLM_API_KEY"), "")
    base_url = os.getenv(cfg.get("base_url_env", "LLM_BASE_URL"), cfg.get("base_url", ""))
    model = os.getenv(cfg.get("model_env", "LLM_MODEL"), cfg.get("model", ""))
    return bool(api_key and base_url and model)


def run(config_path: str, dry_run: bool = False) -> Path:
    cfg = load_config(config_path)
    data = cfg.data
    stats = RunStats(llm_enabled=bool(data.get("llm", {}).get("enabled", False) and _llm_configured(data)))

    state = SeenState(cfg.state_path)
    candidates = collect_candidates(data, stats)
    state.observe(candidates)

    ranked_candidates = rank_items(candidates, data)
    bounded = source_balanced_select(ranked_candidates, cfg.max_candidates, data)
    fresh_ranked = [row for row in bounded if not state.was_pushed(row.item)]
    stats.eligible_count = len(fresh_ranked)
    print(f"[radar] eligible={len(bounded)} unpushed={len(fresh_ranked)}")

    shortlist = fresh_ranked[: cfg.shortlist_size]
    stats.shortlist_count = len(shortlist)
    shortlist = enrich_shortlist(shortlist, data)
    shortlist = analyze_shortlist(shortlist, data)
    stats.llm_used_count = sum(1 for row in shortlist if row.llm is not None)
    stats.llm_failed_count = sum(1 for row in shortlist if "llm_fallback" in row.reasons)
    final_balance_cfg = {"source_balance": data.get("final_source_balance", {"enabled": True, "soft_quota": 4, "min_score_keep": 0.82})}
    final_items = source_balanced_select(shortlist, cfg.top_n, final_balance_cfg)
    stats.final_count = len(final_items)

    now = datetime.now()
    timezone_name = data.get("timezone", "Asia/Shanghai")
    full_report = render_digest(final_items, now, stats=stats, timezone_name=timezone_name)
    telegram_cfg = data.get("telegram_digest", {})
    telegram_digest = render_telegram_digest(
        final_items,
        now,
        timezone_name=timezone_name,
        max_items=int(telegram_cfg.get("max_items", 5)),
    )

    cfg.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = cfg.report_dir / f"radar-{now.strftime('%Y%m%d')}.md"
    report_path.write_text(full_report, encoding="utf-8")
    print(f"[radar] report={report_path} final_items={len(final_items)} telegram_items={min(len(final_items), int(telegram_cfg.get('max_items', 5)))}")

    if dry_run:
        print("[radar] dry-run: publishers and state persistence skipped")
        print("[radar] telegram-preview:\n" + telegram_digest)
        return report_path

    sent = publish_enabled(telegram_digest, data)
    if final_items and sent:
        state.mark_pushed([row.item for row in final_items])
    state.save()
    print(f"[radar] publishers={','.join(sent) if sent else 'none'} state={cfg.state_path}")
    return report_path


def check_llm(config_path: str) -> None:
    cfg = load_config(config_path)
    data = cfg.data
    llm_cfg = data.get("llm", {})
    api_key = os.getenv(llm_cfg.get("api_key_env", "LLM_API_KEY"), "")
    base_url = os.getenv(llm_cfg.get("base_url_env", "LLM_BASE_URL"), llm_cfg.get("base_url", ""))
    model = os.getenv(llm_cfg.get("model_env", "LLM_MODEL"), llm_cfg.get("model", ""))
    if not api_key or not base_url or not model:
        print("[radar] LLM check skipped: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL not fully configured")
        return
    timeout = int(llm_cfg.get("timeout_seconds", 55))
    print("[radar] LLM check models: start")
    print(f"[radar] LLM check models: {'OK' if check_llm_models(base_url, api_key, timeout=min(timeout, 20)) else 'FAIL'}")
    print("[radar] LLM check chat: start")
    print(f"[radar] LLM check chat: {'OK' if check_llm_chat(base_url, api_key, model, timeout=min(timeout, 30)) else 'FAIL'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Research Engineer Radar")
    parser.add_argument("--config", default="config/radar.json")
    parser.add_argument("--dry-run", action="store_true", help="Generate full report and Telegram preview without publishing or persisting seen state")
    parser.add_argument("--check-llm", action="store_true", help="Run minimal OpenAI-compatible LLM connectivity checks")
    args = parser.parse_args(argv)
    if args.check_llm:
        check_llm(args.config)
        return
    run(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
