from __future__ import annotations

import unittest

from radar.eval.benchmark import run_offline
from radar.query.planner import QueryPlan, plan_query
from radar.research.provenance import canonicalize_url, infer_relation, is_noise_link
from radar.research.search import ResearchResult, SourceEdge, SourceNode
from radar.telegram.bot import _GREETING_RE, _first_url, _ordinal, render_search_result


class InteractiveResearchTests(unittest.TestCase):
    def test_fallback_planner_understands_time_and_trace_intent(self) -> None:
        plan = plan_query("找最近一周 Agent Skills 的一手来源并追溯源头", {"llm": {"enabled": False}})
        self.assertEqual(plan.timeframe_days, 7)
        self.assertTrue(plan.primary_only)
        self.assertGreaterEqual(plan.depth, 2)
        self.assertEqual(plan.intent, "source_trace")

    def test_fallback_planner_preserves_negative_constraint(self) -> None:
        plan = plan_query("找 GPU utilization 的工程文章，不要浅教程", {"llm": {"enabled": False}})
        self.assertTrue(plan.exclude_terms)
        self.assertIn("浅教程", plan.exclude_terms[0])

    def test_ordinal_supports_chinese_and_digits(self) -> None:
        self.assertEqual(_ordinal("深挖第2条"), 2)
        self.assertEqual(_ordinal("继续看第三条"), 3)
        self.assertIsNone(_ordinal("继续深挖"))

    def test_direct_url_can_be_used_as_seed(self) -> None:
        self.assertEqual(_first_url("这个继续深挖 https://example.com/a?x=1"), "https://example.com/a?x=1")

    def test_greeting_does_not_become_research_query(self) -> None:
        self.assertIsNotNone(_GREETING_RE.match("hello"))
        self.assertIsNotNone(_GREETING_RE.match("你好！"))

    def test_provenance_filters_navigation_noise(self) -> None:
        self.assertTrue(is_noise_link("https://github.com/login?return_to=/a/b", "Sign in"))
        self.assertTrue(is_noise_link("https://example.com/privacy", "Privacy Policy"))
        self.assertFalse(is_noise_link("https://github.com/openai/openai-python", "Official repository"))

    def test_canonicalize_tracking_url(self) -> None:
        self.assertEqual(canonicalize_url("http://www.github.com/openai/openai-python/?utm_source=x&ref=foo#readme"), "https://github.com/openai/openai-python")

    def test_relation_inference(self) -> None:
        self.assertEqual(infer_relation("https://example.com/post", "https://arxiv.org/abs/1234.5678", "Paper"), "cites")
        self.assertEqual(infer_relation("https://arxiv.org/abs/1234.5678", "https://github.com/a/b", "Official code"), "implements")

    def test_telegram_search_result_exposes_links_and_source_chain(self) -> None:
        plan = QueryPlan(original_query="agent reliability", topic="Agent Reliability", intent="deep_research", timeframe_days=7, keywords=["agent", "reliability"], queries=["agent reliability"], depth=2)
        root = SourceNode(title="Official engineering post", url="https://openai.com/example", source="Web Search", summary="Production reliability lessons.", kind="web", score=0.9, primary_score=0.96)
        child = SourceNode(title="Evaluation paper", url="https://arxiv.org/abs/1234.5678", source="arxiv.org", summary="Evaluation benchmark.", kind="paper", score=0.8, primary_score=0.92, depth=1, discovered_from=root.url, relation="cites")
        result = ResearchResult(plan=plan, nodes=[root, child], edges=[SourceEdge(source_url=root.url, target_url=child.url, relation="cites")])
        text = render_search_result(result)
        self.assertIn("Agent Reliability", text)
        self.assertIn("https://openai.com/example", text)
        self.assertIn("https://arxiv.org/abs/1234.5678", text)
        self.assertIn("引用", text)
        self.assertNotIn("Run Stats", text)

    def test_v1_offline_benchmark_is_green(self) -> None:
        result = run_offline({})
        self.assertEqual(result["passed"], result["total"])
        self.assertEqual(result["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
