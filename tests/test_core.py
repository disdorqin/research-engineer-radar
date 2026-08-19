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
from radar.digest.markdown import render_digest, render_telegram_digest
from radar.models import CollectorResult, LLMAnalysis, RadarItem, RankedItem, RunStats
from radar.processing.normalize import canonical_url, deduplicate_items, title_fingerprint
from radar.publishers.telegram import compact_for_telegram, split_message as split_telegram
from radar.ranking.scorer import rank_items, source_balanced_select
from radar.state.seen import SeenState


BASE_CONFIG = {
    "topic_weights": {
        "agent_engineering": 0.3,
        "engineering_methodology": 0.25,
        "performance_ai_systems": 0.25,
        "frontier_research_tools": 0.2,
    },
    "keywords": {
        "agent_engineering": ["agent", "tool calling", "checkpoint", "evaluation"],
        "engineering_methodology": ["profiling", "bottleneck", "benchmark", "observability"],
        "performance_ai_systems": ["gpu", "batching", "cache", "latency", "throughput"],
        "frontier_research_tools": ["openai", "anthropic", "time series", "forecasting"],
    },
    "methodology_terms": ["profiling", "bottleneck", "benchmark", "evaluation", "observability", "failure analysis"],
    "engineering_terms": ["profiling", "gpu", "batching", "cache", "latency", "throughput", "tool calling", "checkpoint"],
    "production_terms": ["production", "reliability", "observability", "failure", "retry", "checkpoint", "evaluation"],
    "transfer_terms": ["framework", "design", "benchmark", "evaluation", "profiling", "agent", "inference", "forecasting"],
    "action_terms": ["benchmark", "github", "code", "implementation"],
    "source_priority": {"OpenAI": 1.0, "GitHub Search": 0.76, "arXiv": 0.74, "Unknown": 0.2},
    "hype_terms": ["game changer", "magic"],
    "demo_only_terms": ["agent in 5 minutes"],
    "shallow_tutorial_terms": ["for beginners"],
    "ranking_weights": {
        "topic_alignment": 0.18,
        "methodology_value": 0.18,
        "engineering_depth": 0.17,
        "production_value": 0.14,
        "transferability": 0.13,
        "actionability": 0.08,
        "source_quality": 0.07,
        "freshness": 0.03,
        "github_signal": 0.02,
        "hype_penalty": 0.10,
        "demo_only_penalty": 0.10,
        "shallow_tutorial_penalty": 0.07,
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

    def test_methodology_item_ranks_above_hype(self):
        good = RadarItem(
            title="Profiling GPU bottlenecks with observability benchmark",
            url="https://a.example",
            source="OpenAI",
            summary="measure latency throughput and validate optimization",
        )
        hype = RadarItem(title="Game changer AI magic", url="https://b.example", source="Unknown")
        ranked = rank_items([hype, good], BASE_CONFIG)
        self.assertEqual(ranked[0].item.url, "https://a.example")
        self.assertIn("methodology_value", ranked[0].component_scores)
        self.assertIn("engineering_depth", ranked[0].component_scores)

    def test_agent_reliability_beats_demo_only(self):
        mature = RadarItem(
            title="Agent reliability evaluation with checkpoint recovery",
            url="https://a.example",
            source="OpenAI",
            summary="production failure analysis observability tool calling benchmark",
        )
        toy = RadarItem(
            title="Build an agent in 5 minutes",
            url="https://b.example",
            source="Unknown",
            summary="agent demo",
        )
        ranked = rank_items([toy, mature], BASE_CONFIG)
        self.assertEqual(ranked[0].item.url, "https://a.example")
        toy_row = next(row for row in ranked if row.item.url == "https://b.example")
        self.assertGreater(toy_row.component_scores["demo_only_penalty"], 0)

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

    def test_llm_json_parse_methodology_fields(self):
        content = """```json
{"category":"Agent Engineering","long_term_value":9,"methodology_value":10,"engineering_depth":8,"production_value":9,"transferability":9,"novelty":7,"actionability":6,"core_problem":"x","key_takeaway":"y","current_project_relation":"无明显直接关联","suggested_action":"精读"}
```"""
        analysis = parse_analysis(content)
        self.assertAlmostEqual(analysis.methodology_value, 1.0)
        self.assertEqual(analysis.category, "Agent Engineering")
        self.assertEqual(analysis.current_project_relation, "无明显直接关联")
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

    def test_full_report_keeps_debug_but_hides_forced_project_relation(self):
        stats = RunStats()
        stats.add_collector(CollectorResult(source="OpenAI", items=[RadarItem("A", "https://a", "OpenAI")], status="OK", latency_seconds=0.1))
        ranked = RankedItem(
            item=RadarItem(title="Agent Reliability", url="http://example.com", source="OpenAI", summary="agent reliability"),
            score=0.8,
            reasons=["agent_engineering: agent"],
            action="精读",
            component_scores={"methodology_value": 0.8},
            llm=LLMAnalysis(
                category="Agent Engineering",
                core_problem="Agent 长任务失败后如何恢复",
                key_takeaway="checkpoint 加 state validation",
                when_to_recall="设计长任务 Agent 时",
                current_project_relation="无明显直接关联",
                suggested_action="精读",
                long_term_value=0.9,
                methodology_value=0.9,
                engineering_depth=0.8,
                production_value=0.9,
                transferability=0.9,
            ),
        )
        text = render_digest([ranked], stats=stats)
        self.assertIn("Source Health", text)
        self.assertIn("checkpoint 加 state validation", text)
        self.assertNotIn("当前工作可选关联", text)
        self.assertIn("https://example.com", text)

    def test_telegram_digest_is_mobile_first(self):
        ranked = RankedItem(
            item=RadarItem(title="Agent Reliability", url="http://example.com", source="OpenAI", summary="agent reliability"),
            score=0.9,
            action="精读",
            component_scores={"methodology_value": 1.0, "source_quality": 1.0},
            llm=LLMAnalysis(
                category="Agent Engineering",
                core_problem="Agent 长任务失败后如何恢复",
                key_takeaway="不要只 retry，要 checkpoint + state validation",
                when_to_recall="做长任务 Agent 时",
                agent_insight="恢复能力必须成为架构的一部分",
                current_project_relation="无明显直接关联",
                suggested_action="精读",
                long_term_value=1.0,
                methodology_value=1.0,
                engineering_depth=0.9,
                production_value=1.0,
                transferability=1.0,
            ),
        )
        text = render_telegram_digest([ranked], max_items=5)
        self.assertIn("今天最值得看", text)
        self.assertIn("真正值得学", text)
        self.assertIn("Agent 启发", text)
        self.assertNotIn("Source Health", text)
        self.assertNotIn("Deterministic", text)
        self.assertNotIn("当前项目", text)

    def test_config_loading(self):
        cfg = load_config("config/radar.json")
        self.assertGreaterEqual(cfg.top_n, 5)
        self.assertIn("radar_focus", cfg.data)
        self.assertIn("agent_engineering", cfg.data["topic_weights"])
        self.assertIn("methodology_terms", cfg.data)


if __name__ == "__main__":
    unittest.main()
