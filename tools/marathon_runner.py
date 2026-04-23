import json
import os
import subprocess
import sys
from datetime import datetime

import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_DIR = os.path.join(ROOT_DIR, "vault", "evals")
SESSIONS_DIR = os.path.join(EVALS_DIR, "sessions")
PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

SCRIPT_PATH = os.path.join(ROOT_DIR, "tools", "run_eval.py")


def resolve_agent_default_pack(agent: dict, agent_slug: str) -> str:
    eval_block = agent.get("eval") or {}
    return eval_block.get("default_pack") or agent.get("default_pack") or f"{agent_slug}_pack"


def _safe_session_name(batch_id: str) -> str:
    return str(batch_id).replace("/", "__").replace("\\", "__").replace(":", "_")


def _session_path_for(batch_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{_safe_session_name(batch_id)}.json")


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _init_marathon_session(args: dict, marathon_id: str, total_legs: int) -> dict:
    difficulties = args.get("difficulty", [])
    if not isinstance(difficulties, list):
        difficulties = [difficulties]
    return {
        "batch_id": marathon_id,
        "marathon_id": marathon_id,
        "type": "marathon",
        "status": "running",
        "params": args,
        "selected_agents": list(args.get("agents", [])),
        "selected_difficulties": difficulties,
        "runs_per_agent": int(args.get("runs", 1)),
        "review_mode": args.get("review_mode", "score_only"),
        "environment": args.get("environment", "local"),
        "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "controller_pid": os.getpid(),
        "current_leg_index": 0,
        "total_legs": total_legs,
        "completed_legs": [],
        "current_agent": None,
        "current_difficulty": None,
        "current_child_batch_id": None,
        "last_child_batch_id": None,
        "review_progress": 0,
        "review_step": "Queued marathon",
        "events": [],
        "watch_patterns": [],
    }


def _persist_marathon_session(session: dict) -> None:
    session["updated_at"] = datetime.now().isoformat()
    parent_path = _session_path_for(session["marathon_id"])
    _write_json(parent_path, session)
    _write_json(os.path.join(EVALS_DIR, "active_session.json"), session)


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
    total_legs = len(marathon_agents) * len(diff_list)
    marathon_id = args.get("marathon_id") or f"marathon/{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    marathon_session = _init_marathon_session(args, marathon_id, total_legs)
    _persist_marathon_session(marathon_session)

    leg_index = 0
    for agent_slug in marathon_agents:
        if agent_slug not in agent_map:
            print(f"Skipping unknown agent: {agent_slug}")
            continue

        agent = agent_map[agent_slug]
        default_pack = resolve_agent_default_pack(agent, agent_slug)

        for current_diff in diff_list:
            leg_index += 1
            child_batch_id = f"{marathon_id}/{agent_slug}_{current_diff}"
            marathon_session["batch_id"] = child_batch_id
            marathon_session["current_leg_index"] = leg_index
            marathon_session["current_agent"] = agent_slug
            marathon_session["current_difficulty"] = current_diff
            marathon_session["current_child_batch_id"] = child_batch_id
            marathon_session["last_child_batch_id"] = child_batch_id
            marathon_session["review_step"] = f"Launching {agent_slug} / {current_diff}"
            marathon_session["review_progress"] = int(((leg_index - 1) / max(total_legs, 1)) * 100)
            _persist_marathon_session(marathon_session)

            params = {
                "agent": agent_slug,
                "batch_id": child_batch_id,
                "pack": default_pack,
                "environment": environment,
                "type": "batch",
                "difficulty": current_diff,
                "runs": runs_per_agent,
                "turn_profile": "standard",
                "review_mode": review_mode,
                "browser_mode": False,
                "marathon_parent_id": marathon_id,
                "marathon_leg_index": leg_index,
                "marathon_total_legs": total_legs,
                "marathon_selected_agents": marathon_agents,
                "marathon_selected_difficulties": diff_list,
            }

            print("\n==========================================================")
            print(f"STARTING MARATHON RUN: {agent_slug.upper()} | DIFF: {str(current_diff).upper()} ({runs_per_agent} runs)")
            print("==========================================================\n")

            result = subprocess.run([PYTHON_EXE, SCRIPT_PATH, json.dumps(params)])

            leg_status = "completed" if result.returncode == 0 else "failed"
            marathon_session["completed_legs"].append(
                {
                    "agent": agent_slug,
                    "difficulty": current_diff,
                    "batch_id": child_batch_id,
                    "status": leg_status,
                }
            )
            marathon_session["review_progress"] = int((leg_index / max(total_legs, 1)) * 100)
            marathon_session["review_step"] = f"Completed {agent_slug} / {current_diff}"
            _persist_marathon_session(marathon_session)

            if result.returncode != 0:
                print(f"Error during {agent_slug} marathon ({current_diff}).")
            else:
                print(f"Successfully completed marathon batch for {agent_slug} ({current_diff}).")

    marathon_session["status"] = "completed"
    marathon_session["batch_id"] = marathon_session.get("last_child_batch_id") or marathon_id
    marathon_session["review_progress"] = 100
    marathon_session["review_step"] = "Marathon complete"
    marathon_session["completed_at"] = datetime.now().isoformat()
    _persist_marathon_session(marathon_session)


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
