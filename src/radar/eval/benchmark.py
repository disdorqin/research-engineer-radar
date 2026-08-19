from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass

from radar.config import load_config
from radar.query.planner import plan_query
from radar.research.provenance import canonicalize_url, infer_relation, is_noise_link


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str


def run_offline(config: dict | None = None) -> dict:
    config = dict(config or {})
    config["llm"] = {"enabled": False}
    checks: list[Check] = []

    p1 = plan_query("找最近一周 Agent Skills 的一手来源并追溯源头", config)
    checks.append(Check("planner.timeframe", p1.timeframe_days == 7, f"days={p1.timeframe_days}"))
    checks.append(Check("planner.primary", p1.primary_only, f"primary={p1.primary_only}"))
    checks.append(Check("planner.depth", p1.depth >= 2, f"depth={p1.depth}"))
    p2 = plan_query("找 GPU utilization 的工程文章，不要浅教程", config)
    checks.append(Check("planner.exclude", bool(p2.exclude_terms), f"exclude={p2.exclude_terms}"))
    p3 = plan_query("最近24小时 OpenAI agent design 的最新进展", config)
    checks.append(Check("planner.24h", p3.timeframe_days == 1, f"days={p3.timeframe_days}"))

    url = canonicalize_url("http://www.github.com/openai/openai-python/?utm_source=x&ref=foo#readme")
    checks.append(Check("url.canonical", url == "https://github.com/openai/openai-python", url))
    checks.append(Check("noise.github_login", is_noise_link("https://github.com/login?return_to=/foo", "Sign in"), "github login filtered"))
    checks.append(Check("provenance.paper", infer_relation("https://example.com/blog", "https://arxiv.org/abs/1234.5678", "Paper") == "cites", "paper relation"))
    checks.append(Check("provenance.code", infer_relation("https://arxiv.org/abs/1234.5678", "https://github.com/a/b", "Official code") == "implements", "code relation"))

    passed = sum(1 for c in checks if c.passed)
    return {"passed": passed, "total": len(checks), "score": round(passed / max(1, len(checks)), 3), "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Research Navigator V1.0 regression benchmark")
    parser.add_argument("--config", default="config/radar.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config).data if os.path.exists(args.config) else {}
    result = run_offline(cfg)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[navigator-eval] {result['passed']}/{result['total']} score={result['score']}")
        for row in result["checks"]:
            print(f"  {'OK' if row['passed'] else 'FAIL'} {row['name']}: {row['detail']}")
    if result["passed"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
