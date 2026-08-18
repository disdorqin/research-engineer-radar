import tempfile
import unittest
from pathlib import Path

from radar.collectors.rss import parse_feed
from radar.digest.markdown import render_digest
from radar.models import RadarItem, RankedItem
from radar.publishers.telegram import split_message
from radar.ranking.scorer import rank_items
from radar.state.seen import SeenState


class CoreTest(unittest.TestCase):
    def test_parse_atom(self):
        xml = """<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>ML Systems Note</title><link href='https://example.com/a?utm_source=x'/><summary>profiling inference pipeline</summary><updated>2026-08-18T00:00:00Z</updated></entry></feed>"""
        items = parse_feed(xml, "Example")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "ML Systems Note")

    def test_engineering_item_ranks_above_hype(self):
        config = {"topic_weights": {"engineering_systems": 0.6}, "keywords": {"engineering_systems": ["profiling", "inference", "data pipeline"]}, "source_priority": {"OpenAI": 1.0, "Unknown": 0.2}, "hype_terms": ["game changer"]}
        good = RadarItem(title="Profiling inference data pipeline", url="https://a.example", source="OpenAI")
        hype = RadarItem(title="Game changer AI magic", url="https://b.example", source="Unknown")
        ranked = rank_items([hype, good], config)
        self.assertEqual(ranked[0].item.url, "https://a.example")

    def test_seen_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "seen.json"
            item = RadarItem(title="A", url="https://example.com/a", source="X")
            state = SeenState(path)
            self.assertFalse(state.is_seen(item))
            state.mark_pushed([item])
            state.save()
            self.assertTrue(SeenState(path).is_seen(item))

    def test_telegram_split(self):
        parts = split_message("a" * 8100, limit=3900)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(len(part) <= 3900 for part in parts))

    def test_digest(self):
        ranked = RankedItem(item=RadarItem(title="Inference Profiling", url="https://example.com", source="OpenAI", summary="profile serving"), score=0.8, reasons=["engineering_systems: profiling"], action="精读")
        text = render_digest([ranked])
        self.assertIn("今天最值得花时间看的内容", text)
        self.assertIn("Inference Profiling", text)
        self.assertIn("建议动作", text)


if __name__ == "__main__":
    unittest.main()
