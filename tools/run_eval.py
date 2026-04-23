import sys
import os
import json
import asyncio
import logging
import uuid
from datetime import datetime

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.tool import XAgentEvalTool
from tools.watch_patterns import append_watched_event, default_watch_patterns

# Ensure vault exists
EVALS_DIR = os.path.join(ROOT_DIR, "vault", "evals")
os.makedirs(EVALS_DIR, exist_ok=True)
SESSIONS_DIR = os.path.join(EVALS_DIR, "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("dojo_runner")


def _safe_session_name(batch_id: str) -> str:
    return str(batch_id).replace("/", "__").replace("\\", "__").replace(":", "_")


def _session_path_for(batch_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{_safe_session_name(batch_id)}.json")


def _load_json(path: str, default=None):
    fallback = {} if default is None else default
    if not path or not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _compute_marathon_progress(leg_index: int, total_legs: int, child_percent: int | None) -> int:
    total = max(int(total_legs or 1), 1)
    leg = max(int(leg_index or 1), 1)
    pct = max(0, min(int(child_percent or 0), 100))
    return int((((leg - 1) + (pct / 100.0)) / total) * 100)


def _init_marathon_parent(params: dict, parent_id: str, batch_id: str, eval_inputs: dict) -> dict:
    difficulties = params.get("marathon_selected_difficulties") or [params.get("difficulty", "mixed")]
    agents = params.get("marathon_selected_agents") or [params.get("agent")]
    leg_index = int(params.get("marathon_leg_index", 1) or 1)
    total_legs = int(params.get("marathon_total_legs", 1) or 1)
    return {
        "batch_id": batch_id,
        "marathon_id": parent_id,
        "type": "marathon",
        "status": "running",
        "params": {
            "agents": agents,
            "difficulty": difficulties,
            "runs": params.get("runs", 1),
            "environment": params.get("environment", "local"),
            "review_mode": params.get("review_mode", "full"),
        },
        "selected_agents": agents,
        "selected_difficulties": difficulties,
        "current_leg_index": leg_index,
        "total_legs": total_legs,
        "current_agent": params.get("agent"),
        "current_difficulty": params.get("difficulty", "mixed"),
        "current_child_batch_id": batch_id,
        "last_child_batch_id": batch_id,
        "current_run_idx": 0,
        "total_runs": eval_inputs["runs"],
        "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "review_progress": _compute_marathon_progress(leg_index, total_legs, 0),
        "review_step": f"{params.get('agent')} / {params.get('difficulty', 'mixed')}: queued",
        "events": [],
        "matched_signals": [],
        "watch_patterns": default_watch_patterns("eval"),
    }


async def run_dojo_mission(params: dict):
    """
    Translates Dojo UI params to XAgentEvalTool inputs and executes.
    Updates active_session.json for Hub polling.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M")
    agent_slug = params.get("agent", "unknown")

    generated_id = f"{date_str}/{agent_slug}_{time_str}"
    batch_id = params.get("batch_id") or params.get("rerun_batch_id") or generated_id
    is_rerun = bool(params.get("rerun_batch_id"))
    marathon_parent_id = params.get("marathon_parent_id")
    marathon_leg_index = int(params.get("marathon_leg_index", 1) or 1)
    marathon_total_legs = int(params.get("marathon_total_legs", 1) or 1)

    # Map Dojo params to Evaluator inputs
    eval_inputs = {
        "target_agent": params.get("agent"),
        "batch_id": batch_id,
        "scenario_pack": params.get("pack"),
        "environment": params.get("environment", "local"),
        "difficulty": params.get("difficulty", "mixed"),
        "runs": int(params.get("runs", 1)),
        "max_turns": params.get("turn_profile", 12),
        "scoring_rubric": params.get("scoring_rubric", "default_v1"),
        "browser_mode": params.get("browser_mode", True),
        "review_mode": params.get("review_mode", "full"),
        "rerun_failed_only": is_rerun,
        "sim_user_model": params.get("sim_user_model"),
    }

    tp = params.get("turn_profile")
    tp_map = {"short": 5, "standard": 12, "long": 20, "stress": 35}
    if isinstance(tp, str) and tp in tp_map:
        eval_inputs["max_turns"] = tp_map[tp]
    elif isinstance(tp, int):
        eval_inputs["max_turns"] = tp

    tool = XAgentEvalTool()
    tool.batch_id = batch_id

    session_info = {
        "batch_id": batch_id,
        "status": "running",
        "params": params,
        "started_at": datetime.now().isoformat(),
        "controller_pid": os.getpid(),
        "current_run_idx": 0,
        "total_runs": eval_inputs["runs"],
        "is_rerun": is_rerun,
        "watch_patterns": default_watch_patterns("eval"),
        "events": [],
        "matched_signals": [],
    }

    active_session_path = os.path.join(EVALS_DIR, "active_session.json")
    batch_session_path = _session_path_for(batch_id)
    parent_session_path = _session_path_for(marathon_parent_id) if marathon_parent_id else None

    def persist_parent_session(status=None, detail=None, error=None, step=None, percent=None, source="dojo_runner"):
        if not marathon_parent_id:
            return
        parent = _load_json(parent_session_path, _init_marathon_parent(params, marathon_parent_id, batch_id, eval_inputs))
        parent["batch_id"] = batch_id
        parent["marathon_id"] = marathon_parent_id
        parent["type"] = "marathon"
        parent["current_agent"] = params.get("agent")
        parent["current_difficulty"] = params.get("difficulty", "mixed")
        parent["current_child_batch_id"] = batch_id
        parent["last_child_batch_id"] = batch_id
        parent["current_run_id"] = session_info.get("current_run_id")
        parent["current_run_idx"] = session_info.get("current_run_idx")
        parent["total_runs"] = session_info.get("total_runs")
        parent["current_leg_index"] = marathon_leg_index
        parent["total_legs"] = marathon_total_legs
        parent["review_step"] = f"{params.get('agent')} / {params.get('difficulty', 'mixed')}: {step or session_info.get('review_step') or status or 'running'}"
        parent["review_progress"] = _compute_marathon_progress(marathon_leg_index, marathon_total_legs, percent if percent is not None else session_info.get("review_progress"))
        parent["updated_at"] = datetime.now().isoformat()
        parent["status"] = "running"
        if error:
            parent["last_error"] = error
        state_detail = detail or error or step or status or ""
        phase = "failed" if error else "running"
        parent.update(
            append_watched_event(
                parent,
                kind="eval",
                status=status or session_info.get("status") or "running",
                phase=phase,
                detail=state_detail,
                step=parent.get("review_step"),
                percent=parent.get("review_progress"),
                source=source,
                extra={
                    "run_id": session_info.get("current_run_id"),
                    "idx": session_info.get("current_run_idx"),
                    "total_runs": session_info.get("total_runs"),
                    "leg_index": marathon_leg_index,
                    "total_legs": marathon_total_legs,
                    "difficulty": params.get("difficulty", "mixed"),
                    "child_batch_id": batch_id,
                },
            )
        )
        for path in (parent_session_path, active_session_path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(parent, f)

    def update_session(run_id=None, idx=None, status=None, step=None, percent=None, error=None, detail=None, source="dojo_runner"):
        if run_id:
            session_info["current_run_id"] = run_id
        if idx is not None:
            session_info["current_run_idx"] = idx
        if status:
            session_info["status"] = status
        if step:
            session_info["review_step"] = step
        if percent is not None:
            session_info["review_progress"] = percent
        if error:
            session_info["error"] = error
        session_info["updated_at"] = datetime.now().isoformat()
        session_info["session_path"] = batch_session_path
        state_detail = detail or error or step or status or ""
        phase = "failed" if (status == "failed" or error) else "running"
        if status == "completed":
            phase = "completed"
        session_info.update(
            append_watched_event(
                session_info,
                kind="eval",
                status=status or session_info.get("status"),
                phase=phase,
                detail=state_detail,
                step=step or session_info.get("review_step"),
                percent=percent if percent is not None else session_info.get("review_progress"),
                source=source,
                extra={
                    "run_id": run_id or session_info.get("current_run_id"),
                    "idx": idx if idx is not None else session_info.get("current_run_idx"),
                    "total_runs": session_info.get("total_runs"),
                },
            )
        )
        with open(batch_session_path, "w", encoding="utf-8") as f:
            json.dump(session_info, f)
        if marathon_parent_id:
            persist_parent_session(status=status, detail=detail, error=error, step=step, percent=percent, source=source)
        else:
            with open(active_session_path, "w", encoding="utf-8") as f:
                json.dump(session_info, f)

    update_session(status="running", detail="Dojo mission dispatched.")

    context = {
        "local_url": "http://127.0.0.1:3000",
        "env_url": "https://x-agent.ai",
    }

    try:
        if await tool.prepare(context, eval_inputs):
            def on_progress(step: str, percent: int, **extra):
                logger.info(f"Dojo Progress: {step} ({percent}%)")
                update_session(
                    run_id=extra.get("run_id"),
                    idx=extra.get("idx"),
                    step=step,
                    percent=percent,
                    detail=step,
                    source="progress_callback",
                )

            result = await tool.execute(context, progress_callback=on_progress)

            if result.status == "success":
                verdict = result.data.get("verdict") or "unknown"
                update_session(status="completed", percent=100, detail=f"Batch completed. Verdict: {verdict}")
                logger.info(f"Dojo Batch {batch_id} complete. Verdict: {result.data.get('verdict')}")
            else:
                update_session(status="failed", error=str(result.data.get("error", result.summary)), detail=str(result.data.get("error", result.summary)))
                logger.error(f"Dojo Batch {batch_id} failed: {result.summary}")
        else:
            update_session(status="failed", error="Tool preparation failed", detail="Tool preparation failed")
            logger.error("Tool preparation failed.")
    except Exception as e:
        update_session(status="failed", error=str(e), detail=str(e))
        logger.error(f"Dojo execution error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Missing params JSON.")
        sys.exit(1)

    try:
        input_params = json.loads(sys.argv[1])
        asyncio.run(run_dojo_mission(input_params))
    except Exception as ex:
        logger.error(f"Runner entry failure: {ex}")
