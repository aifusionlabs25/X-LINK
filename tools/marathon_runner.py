import json
import os
import subprocess
import sys

import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

SCRIPT_PATH = os.path.join(ROOT_DIR, "tools", "run_eval.py")


def resolve_agent_default_pack(agent: dict, agent_slug: str) -> str:
    eval_block = agent.get("eval") or {}
    return eval_block.get("default_pack") or agent.get("default_pack") or f"{agent_slug}_pack"


def run_marathon(args: dict) -> None:
    marathon_agents = args.get("agents", [])
    runs_per_agent = int(args.get("runs", 1))
    difficulty = args.get("difficulty", "medium")
    environment = args.get("environment", "local")
    review_mode = args.get("review_mode", "score_only")

    agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
    with open(agents_path, "r", encoding="utf-8") as f:
        agents_data = yaml.safe_load(f).get("agents", [])

    agent_map = {a["slug"]: a for a in agents_data}
    diff_list = difficulty if isinstance(difficulty, list) else [difficulty]

    for agent_slug in marathon_agents:
        if agent_slug not in agent_map:
            print(f"Skipping unknown agent: {agent_slug}")
            continue

        agent = agent_map[agent_slug]
        default_pack = resolve_agent_default_pack(agent, agent_slug)

        for current_diff in diff_list:
            params = {
                "agent": agent_slug,
                "pack": default_pack,
                "environment": environment,
                "type": "batch",
                "difficulty": current_diff,
                "runs": runs_per_agent,
                "turn_profile": "standard",
                "review_mode": review_mode,
                "browser_mode": False,
            }

            print("\n==========================================================")
            print(f"STARTING MARATHON RUN: {agent_slug.upper()} | DIFF: {str(current_diff).upper()} ({runs_per_agent} runs)")
            print("==========================================================\n")

            result = subprocess.run([PYTHON_EXE, SCRIPT_PATH, json.dumps(params)])

            if result.returncode != 0:
                print(f"Error during {agent_slug} marathon ({current_diff}).")
            else:
                print(f"Successfully completed marathon batch for {agent_slug} ({current_diff}).")


def main() -> int:
    if len(sys.argv) <= 1:
        print("No parameters provided.")
        return 1

    try:
        args = json.loads(sys.argv[1])
    except Exception as e:
        print(f"Error parsing marathon arguments: {e}")
        return 1

    print("Initializing X-LINK Marathon Runner...")
    run_marathon(args)
    print("\nAll marathon runs complete. Check the Hub Results tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
