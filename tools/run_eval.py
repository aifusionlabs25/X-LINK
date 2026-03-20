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

# Ensure vault exists
EVALS_DIR = os.path.join(ROOT_DIR, "vault", "evals")
os.makedirs(EVALS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("dojo_runner")

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
    batch_id = params.get("rerun_batch_id") or generated_id
    is_rerun = bool(params.get("rerun_batch_id"))
    
    # Map Dojo params to Evaluator inputs
    # Dojo: { agent, pack, environment, run_type, difficulty, runs, turn_profile, review_mode, browser_mode }
    eval_inputs = {
        "target_agent": params.get("agent"),
        "scenario_pack": params.get("pack"),
        "environment": params.get("environment", "local"),
        "difficulty": params.get("difficulty", "mixed"),
        "runs": int(params.get("runs", 1)),
        "max_turns": params.get("turn_profile", 12), # If we get 'standard' etc, we could map them
        "scoring_rubric": params.get("scoring_rubric", "default_v1"),
        "browser_mode": params.get("browser_mode", True),
        "review_mode": params.get("review_mode", "full"),
        "rerun_failed_only": is_rerun
    }
    
    # Handle turn profile mapping
    tp = params.get("turn_profile")
    tp_map = {"short": 5, "standard": 12, "long": 20, "stress": 35}
    if isinstance(tp, str) and tp in tp_map:
        eval_inputs["max_turns"] = tp_map[tp]
    elif isinstance(tp, int):
        eval_inputs["max_turns"] = tp

    # Initialize Tool
    tool = XAgentEvalTool()
    tool.batch_id = batch_id
    
    # Update active_session.json
    session_info = {
        "batch_id": batch_id,
        "status": "running",
        "params": params,
        "started_at": datetime.now().isoformat(),
        "current_run_idx": 0,
        "total_runs": eval_inputs["runs"],
        "is_rerun": is_rerun
    }
    
    session_path = os.path.join(EVALS_DIR, "active_session.json")
    def update_session(run_id=None, idx=None, status=None, step=None, percent=None, error=None):
        if run_id: session_info["current_run_id"] = run_id
        if idx is not None: session_info["current_run_idx"] = idx
        if status: session_info["status"] = status
        if step: session_info["review_step"] = step
        if percent is not None: session_info["review_progress"] = percent
        if error: session_info["error"] = error
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session_info, f)

    update_session()


    # Prep & Execute
    context = {
        "local_url": "http://127.0.0.1:3000",
        "env_url": "https://x-agent.ai"
    }
    
    try:
        if await tool.prepare(context, eval_inputs):
            def on_progress(step: str, percent: int):
                logger.info(f"Dojo Progress: {step} ({percent}%)")
                update_session(step=step, percent=percent)

            result = await tool.execute(context, progress_callback=on_progress)
            
            if result.status == "success":
                update_session(status="completed", percent=100)
                logger.info(f"Dojo Batch {batch_id} complete. Verdict: {result.data.get('verdict')}")
            else:
                update_session(status="failed", error=str(result.data.get("error", result.summary)))
                logger.error(f"Dojo Batch {batch_id} failed: {result.summary}")
        else:
            update_session(status="failed", error="Tool preparation failed")
            logger.error("Tool preparation failed.")
    except Exception as e:
        update_session(status="failed", error=str(e))
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
