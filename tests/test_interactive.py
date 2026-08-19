from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from radar.query.planner import QueryPlan, plan_query
from radar.research.search import ResearchResult, SourceEdge, SourceNode
from radar.telegram.bot import _ordinal, render_search_result


class InteractiveResearchTests(unittest.TestCase):
    def test_fallback_planner_understands_time_and_trace_intent(self) -> None:
        with patch.dict(os.environ, {"LLM_API_KEY": "", "LLM_BASE_URL": "", "LLM_MODEL": ""}):
            plan = plan_query("找最近一周 Agent Skills 的一手来源并追溯源头", {})
        self.assertEqual(plan.timeframe_days, 7)
        self.assertTrue(plan.primary_only)
        self.assertGreaterEqual(plan.depth, 2)
        self.assertIn(plan.intent, {"source_trace", "deep_research"})

    def test_ordinal_supports_chinese_and_digits(self) -> None:
        self.assertEqual(_ordinal("深挖第2条"), 2)
        self.assertEqual(_ordinal("继续看第三条"), 3)
        self.assertIsNone(_ordinal("继续深挖"))

    def test_telegram_search_result_exposes_links_and_source_chain(self) -> None:
        plan = QueryPlan(
            original_query="agent reliability",
            topic="Agent Reliability",
            intent="deep_research",
            timeframe_days=7,
            keywords=["agent", "reliability"],
            queries=["agent reliability"],
            depth=2,
        )
        root = SourceNode(
            title="Official engineering post",
            url="https://openai.com/example",
            source="Web Search",
            summary="Production reliability lessons.",
            kind="web",
            score=0.9,
            primary_score=0.96,
        )
        child = SourceNode(
            title="Evaluation paper",
            url="https://arxiv.org/abs/1234.5678",
            source="arxiv.org",
            summary="Evaluation benchmark.",
            kind="paper",
            score=0.8,
            primary_score=0.92,
            depth=1,
            discovered_from=root.url,
            relation="links_to",
        )
        result = ResearchResult(
            plan=plan,
            nodes=[root, child],
            edges=[SourceEdge(source_url=root.url, target_url=child.url)],
        )
        text = render_search_result(result)
        self.assertIn("Agent Reliability", text)
        self.assertIn("https://openai.com/example", text)
        self.assertIn("https://arxiv.org/abs/1234.5678", text)
        self.assertIn("来源链", text)
        self.assertNotIn("Run Stats", text)


if __name__ == "__main__":
    unittest.main()
