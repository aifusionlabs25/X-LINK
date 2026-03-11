"""
X-Agent Eval v1 — Live Validation Script
Runs 3 evals against Morgan, saves artifacts, and prints results.
"""

import asyncio
import json
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.tool import XAgentEvalTool


async def main():
    tool = XAgentEvalTool()
    result = await tool.run(
        context={
            "config_dir": os.path.join(ROOT_DIR, "config"),
            "vault_dir": os.path.join(ROOT_DIR, "vault"),
        },
        inputs={
            "target_agent": "Morgan",
            "scenario_pack": "default_pack",
            "runs": 3,
            "difficulty": "mixed",
            "max_turns": 4,
            "scoring_rubric": "default_v1",
        },
    )

    print("=" * 60)
    print("LIVE EVAL RESULTS")
    print("=" * 60)
    print(f"Status:      {result.status}")
    print(f"Summary:     {result.summary}")
    data = result.data
    print(f"Batch ID:    {data.get('batch_id')}")
    print(f"Passed:      {data.get('passed')}/{data.get('total_runs')}")
    print(f"Pass Rate:   {data.get('pass_rate')}%")
    print(f"Avg Score:   {data.get('average_score')}/100")
    print(f"Verdict:     {data.get('verdict')}")
    print(f"Artifacts:   {len(result.artifacts)} files")
    print(f"Run IDs:     {data.get('run_ids')}")

    if data.get("category_averages"):
        print("\nCategory Averages:")
        for k, v in data["category_averages"].items():
            print(f"  {k}: {v}/5.0")

    if data.get("top_failure_categories"):
        print(f"\nTop Failures: {data['top_failure_categories']}")

    print("\nArtifact paths:")
    for a in result.artifacts:
        print(f"  {a}")


if __name__ == "__main__":
    asyncio.run(main())
