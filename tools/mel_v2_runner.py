import argparse
import asyncio
import json
import sys

from tools.mel_v2.engine import run_evolution_v2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MEL v2 Evolution Engine")
    parser.add_argument("--agent", required=True, help="Agent slug")
    parser.add_argument("--pack", default="default_pack", help="Scenario pack")
    parser.add_argument("--scenarios", type=int, default=3, help="Number of scenarios per eval")
    parser.add_argument("--turns", type=int, default=8, help="Max turns per scenario")
    parser.add_argument("--difficulty", default="mixed", help="Scenario difficulty")
    parser.add_argument("--seed", type=int, default=7, help="Deterministic seed")
    args = parser.parse_args()

    result = asyncio.run(
        run_evolution_v2(
            agent_slug=args.agent,
            scenario_pack=args.pack,
            num_scenarios=args.scenarios,
            max_turns=args.turns,
            difficulty=args.difficulty,
            seed=args.seed,
        )
    )
    sys.stdout.write(json.dumps(result, indent=2))
