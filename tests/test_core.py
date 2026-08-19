import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from radar.ai.analyzer import analyze_shortlist, parse_analysis
from radar.collectors.github_search import build_github_query
from radar.collectors.rss import collect_rss, parse_feed
from radar.collectors.sitemap import parse_sitemap
from radar.config import load_config
from radar.digest.markdown import render_digest
from radar.models import CollectorResult, LLMAnalysis, RadarItem, RankedItem, RunStats
from radar.processing.normalize import canonical_url, deduplicate_items, title_fingerprint
from radar.publishers.telegram import compact_for_telegram, split_message as split_telegram
from radar.ranking.scorer import rank_items, source_balanced_select
from radar.state.seen import SeenState


BASE_CONFIG = {
    "topic_weights": {"engineering_systems": 0.6, "paper_research": 0.4},
    "keywords": {
        "engineering_systems": ["profiling", "inference", "data pipeline", "serving", "benchmark"],
        "paper_research": ["time series", "forecasting", "concept drift", "paper"],
    },
    "engineering_terms": ["profiling", "inference", "pipeline", "benchmark", "serving"],
    "action_terms": ["benchmark", "github", "code", "implementation"],
    "project_transfer_terms": ["time series", "forecasting", "concept drift", "electricity"],
    "source_priority": {"OpenAI": 1.0, "GitHub Search": 0.74, "arXiv": 0.72, "Unknown": 0.2},
    "hype_terms": ["game changer", "magic"],
    "ranking_weights": {
        "topic_alignment": 0.28,
        "engineering_value": 0.2,
        "source_quality": 0.14,
        "freshness": 0.1,
        "actionability": 0.12,
        "project_transferability": 0.1,
        "github_signal": 0.06,
        "hype_penalty": 0.12,
    },
}


class CoreTest(unittest.TestCase):
    def test_parse_atom(self):
        xml = """<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>ML Systems Note</title><link href='https://example.com/a?utm_source=x'/><summary>profiling inference pipeline</summary><updated>2026-08-18T00:00:00Z</updated></entry></feed>"""
        items = parse_feed(xml, "Example")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "ML Systems Note")

    def test_parse_sitemap(self):
        xml = """<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://www.anthropic.com/news/system-cards</loc><lastmod>2026-08-18T00:00:00Z</lastmod></url><url><loc>https://www.anthropic.com/company/about</loc></url></urlset>"""
        items = parse_sitemap(xml, "Anthropic", include_patterns=["/news/"], limit=3)
        self.assertEqual(len(items), 1)
        self.assertIn("System Cards", items[0].title)

    def test_canonical_and_batch_dedup(self):
        a = RadarItem(title="A", url="https://Example.com/x/?utm_source=a", source="X", summary="short")
        b = RadarItem(title="A copy", url="https://example.com/x?ref=foo", source="Y", summary="a much longer summary")
        deduped = deduplicate_items([a, b])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(canonical_url(deduped[0].url), "https://example.com/x")
        self.assertIn("longer", deduped[0].summary)
        self.assertIn("Y", deduped[0].raw["merged_sources"])

    def test_title_fingerprint_cross_source_dedup(self):
        a = RadarItem(title="A Scalable Pipeline for LLM Serving", url="https://arxiv.org/abs/1", source="arXiv")
        b = RadarItem(title="A scalable pipeline for LLM serving!", url="https://example.com/paper", source="Blog")
        deduped = deduplicate_items([a, b])
        self.assertEqual(title_fingerprint(a.title), title_fingerprint(b.title))
        self.assertEqual(len(deduped), 1)

    def test_collector_failure_isolation(self):
        with patch("radar.collectors.rss._fetch_text", side_effect=RuntimeError("boom")):
            results = collect_rss([{"name": "Broken", "url": "https://example.com/rss"}])
        self.assertEqual(results[0].status, "FAIL")
        self.assertEqual(results[0].items, [])

    def test_dynamic_github_date(self):
        now = datetime(2026, 8, 19, tzinfo=timezone.utc)
        query = build_github_query("ml systems stars:>300", lookback_days=7, now=now)
        self.assertIn("pushed:>2026-08-12", query)
        self.assertNotIn("2026-01-01", query)

    def test_engineering_item_ranks_above_hype(self):
        good = RadarItem(title="Profiling inference data pipeline benchmark", url="https://a.example", source="OpenAI")
        hype = RadarItem(title="Game changer AI magic", url="https://b.example", source="Unknown")
        ranked = rank_items([hype, good], BASE_CONFIG)
        self.assertEqual(ranked[0].item.url, "https://a.example")
        self.assertIn("engineering_value", ranked[0].component_scores)

    def test_forecast_relevant_beats_unrelated_theory(self):
        relevant = RadarItem(title="Concept drift benchmark for time series forecasting", url="https://a.example", source="arXiv", tags=["paper"])
        unrelated = RadarItem(title="A proof of an unrelated graph theorem", url="https://b.example", source="arXiv", tags=["paper"])
        ranked = rank_items([unrelated, relevant], BASE_CONFIG)
        self.assertEqual(ranked[0].item.url, "https://a.example")

    def test_old_popular_github_repo_penalty(self):
        old_repo = RadarItem(
            title="old/repo (90000★)",
            url="https://github.com/old/repo",
            source="GitHub Search",
            summary="inference serving benchmark",
            raw={"stars": 90000, "forks": 10000, "created_at": "2020-01-01T00:00:00Z"},
        )
        ranked = rank_items([old_repo], BASE_CONFIG)[0]
        self.assertGreater(ranked.component_scores["old_popular_penalty"], 0)

    def test_source_balance(self):
        rows = []
        for i in range(5):
            rows.append(RankedItem(RadarItem(f"A{i}", f"https://a/{i}", "arXiv"), score=0.5 - i * 0.01))
        rows.append(RankedItem(RadarItem("GitHub useful", "https://g", "GitHub Search"), score=0.45))
        selected = source_balanced_select(rows, 4, {"source_balance": {"enabled": True, "soft_quota": 2, "min_score_keep": 0.9}})
        self.assertIn("GitHub Search", {row.item.source for row in selected})

    def test_seen_state_tracks_seen_and_pushed_separately(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "seen.json"
            item = RadarItem(title="A", url="https://example.com/a", source="X")
            state = SeenState(path)
            state.observe([item])
            self.assertTrue(state.is_seen(item))
            self.assertFalse(state.was_pushed(item))
            state.mark_pushed([item])
            state.save()
            loaded = SeenState(path)
            self.assertTrue(loaded.was_pushed(item))
            self.assertIn("last_seen_at", next(iter(loaded.records.values())))

    def test_llm_json_parse(self):
        content = "```json\n{\"relevance\": 8, \"engineering_value\": 9, \"novelty\": 7, \"actionability\": 6, \"project_transferability\": 5, \"what_it_is\": \"x\", \"why_it_matters\": \"y\", \"suggested_action\": \"精读\"}\n```"
        analysis = parse_analysis(content)
        self.assertAlmostEqual(analysis.relevance, 0.8)
        self.assertEqual(analysis.suggested_action, "精读")

    def test_llm_fallback_when_unconfigured(self):
        row = RankedItem(RadarItem("A", "https://example.com", "OpenAI"), score=0.7)
        with patch.dict(os.environ, {}, clear=True):
            out = analyze_shortlist([row], {"llm": {"enabled": True}})
        self.assertIsNone(out[0].llm)
        self.assertEqual(out[0].score, 0.7)

    def test_publishers_split_and_compact(self):
        text = "a" * 8100
        self.assertTrue(all(len(part) <= 3900 for part in split_telegram(text)))
        compact = compact_for_telegram("排序信号：x\n" + ("a" * 13000), max_chars=200)
        self.assertLessEqual(len(compact), 260)

    def test_digest_uses_llm_analysis_and_stats(self):
        stats = RunStats()
        stats.add_collector(CollectorResult(source="OpenAI", items=[RadarItem("A", "https://a", "OpenAI")], status="OK", latency_seconds=0.1))
        ranked = RankedItem(
            item=RadarItem(title="Inference Profiling", url="https://example.com", source="OpenAI", summary="profile serving"),
            score=0.8,
            reasons=["engineering_systems: profiling"],
            action="尝试",
            component_scores={"engineering_value": 0.8},
            llm=LLMAnalysis(what_it_is="推理性能分析实践", why_it_matters="能直接学习 profiling 方法", ability_tree_relation="训练系统判断力", current_project_relation="可迁移到预测流水线瓶颈定位", suggested_action="尝试", relevance=0.9, engineering_value=0.9, actionability=0.8),
        )
        text = render_digest([ranked], stats=stats)
        self.assertIn("Source Health", text)
        self.assertIn("推理性能分析实践", text)
        self.assertIn("预测流水线瓶颈定位", text)

    def test_config_loading(self):
        cfg = load_config("config/radar.json")
        self.assertGreaterEqual(cfg.top_n, 5)
        self.assertIn("user_profile", cfg.data)


if __name__ == "__main__":
    unittest.main()
