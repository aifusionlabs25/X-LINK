from fastapi import APIRouter, HTTPException
import os
import yaml
import glob
import json
import subprocess
import sys
import logging
from datetime import datetime
from typing import Optional

router = APIRouter()

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
EVALS_DIR = os.path.join(ROOT_DIR, "vault", "evals")
BATCHES_DIR = os.path.join(EVALS_DIR, "batches")
RUNS_DIR = os.path.join(EVALS_DIR, "runs")
SESSIONS_DIR = os.path.join(EVALS_DIR, "sessions")
PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable


def _load_agents_index() -> dict:
    agents_path = os.path.join(CONFIG_DIR, "agents.yaml")
    if not os.path.exists(agents_path):
        return {}

    with open(agents_path, "r", encoding="utf-8") as f:
        agents = yaml.safe_load(f).get("agents", [])

    index = {}
    for agent in agents:
        slug = str(agent.get("slug") or "").strip().lower()
        if slug:
            index[slug] = agent
    return index


def _normalize_eval_launch_params(params: dict) -> dict:
    normalized = dict(params or {})
    agents_index = _load_agents_index()

    agent_slug = str(normalized.get("agent") or "").strip().lower()
    pack_name = str(normalized.get("pack") or "").strip()

    if not agent_slug or agent_slug not in agents_index:
        return normalized

    agent = agents_index[agent_slug]
    eval_block = agent.get("eval") or {}
    allowed_packs = [str(pack).strip() for pack in (eval_block.get("allowed_packs") or []) if str(pack).strip()]
    default_pack = str(eval_block.get("default_pack") or "").strip()

    if pack_name and allowed_packs and pack_name not in allowed_packs:
        owning_agents = []
        for slug, cfg in agents_index.items():
            owner_allowed = [str(pack).strip() for pack in ((cfg.get("eval") or {}).get("allowed_packs") or []) if str(pack).strip()]
            if pack_name in owner_allowed:
                owning_agents.append(slug)

        if len(owning_agents) == 1:
            normalized["agent"] = owning_agents[0]
            owner_eval = (agents_index[owning_agents[0]].get("eval") or {})
            owner_allowed = [str(pack).strip() for pack in (owner_eval.get("allowed_packs") or []) if str(pack).strip()]
            if pack_name not in owner_allowed and owner_eval.get("default_pack"):
                normalized["pack"] = str(owner_eval["default_pack"]).strip()
        elif default_pack:
            normalized["pack"] = default_pack
    elif not pack_name and default_pack:
        normalized["pack"] = default_pack

    return normalized


def _safe_session_name(batch_id: str) -> str:
    return str(batch_id).replace("/", "__").replace("\\", "__").replace(":", "_")


def _session_path_for(batch_id: str) -> str:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return os.path.join(SESSIONS_DIR, f"{_safe_session_name(batch_id)}.json")


def _pid_is_running(pid: Optional[int]) -> bool:
    try:
        pid_int = int(pid or 0)
    except Exception:
        return False
    if pid_int <= 0:
        return False
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid_int}"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        return str(pid_int) in output and "No tasks are running" not in output
    except Exception:
        return False


def _taskkill_pid(pid: Optional[int]) -> bool:
    try:
        pid_int = int(pid or 0)
    except Exception:
        return False
    if pid_int <= 0:
        return False
    try:
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid_int)], shell=True)
        return True
    except Exception:
        return False


def _kill_dojo_processes() -> bool:
    killed = False
    try:
        ps_cmd = (
            "powershell -Command "
            "\"Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'python.exe' -and "
            "($_.CommandLine -match 'marathon_runner.py' -or $_.CommandLine -match 'run_eval.py') } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }\""
        )
        subprocess.call(ps_cmd, shell=True)
        killed = True
    except Exception:
        pass
    return killed


def _write_session_payload(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _clear_active_session_file() -> None:
    active_path = os.path.join(EVALS_DIR, "active_session.json")
    if os.path.exists(active_path):
        os.remove(active_path)


def _mark_session_stopped(session: dict, reason: str = "Batch manually stopped.") -> dict:
    payload = dict(session or {})
    payload["status"] = "stopped"
    payload["updated_at"] = datetime.now().isoformat()
    payload["review_step"] = reason
    payload["review_progress"] = int(payload.get("review_progress") or 0)
    payload["error"] = reason
    return payload

@router.get("/config")
async def get_dojo_config():
    """Aggregates all config-driven data for the Dojo RUN cockpit."""
    try:
        # 1. Load Agents
        agents = []
        agents_path = os.path.join(CONFIG_DIR, "agents.yaml")
        if os.path.exists(agents_path):
            with open(agents_path, "r", encoding="utf-8") as f:
                agents = yaml.safe_load(f).get("agents", [])

        # 2. Load Profiles (Difficulty, Counts, Review Modes, Envs)
        profiles = {}
        profiles_path = os.path.join(CONFIG_DIR, "dojo_profiles.yaml")
        if os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as f:
                profiles = yaml.safe_load(f)

        # 3. Load Scenario Packs
        packs = []
        scenarios_dir = os.path.join(CONFIG_DIR, "eval_scenarios")
        if os.path.exists(scenarios_dir):
            for f in os.listdir(scenarios_dir):
                if f.endswith(".yaml") and f != "template.yaml":
                    packs.append(f.replace(".yaml", ""))

        return {
            "agents": agents,
            "profiles": profiles,
            "scenario_packs": packs
        }
    except Exception as e:
        logging.error(f"Dojo config load failure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/start")
async def start_eval(params: dict):
    """Launches an eval batch via subprocess."""
    # params: { agent, pack, environment, run_type, difficulty, runs, turn_profile, review_mode, browser_mode, rerun_batch_id }
    try:
        params = _normalize_eval_launch_params(params)
        # Build the command for the tool wrapper (to be created)
        # We'll use a new wrapper 'tools/run_eval.py' that takes these JSON params
        script_path = os.path.join(ROOT_DIR, "tools", "run_eval.py")
        if not params.get("batch_id"):
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H%M%S")
            params["batch_id"] = params.get("rerun_batch_id") or f"{date_str}/{params.get('agent', 'agent')}_{time_str}"
        
        # Write intended session info to track active batch
        session_info = {
            "status": "starting",
            "params": params,
            "timestamp": datetime.now().isoformat(),
            "batch_id": params["batch_id"],
        }
        os.makedirs(EVALS_DIR, exist_ok=True)
        with open(os.path.join(EVALS_DIR, "active_session.json"), "w", encoding="utf-8") as f:
            json.dump(session_info, f)
        with open(_session_path_for(params["batch_id"]), "w", encoding="utf-8") as f:
            json.dump(session_info, f)

        # Launch non-blocking
        # Pass params as a JSON string to the wrapper
        proc = subprocess.Popen([PYTHON_EXE, script_path, json.dumps(params)])
        session_info["launcher_pid"] = proc.pid
        _write_session_payload(os.path.join(EVALS_DIR, "active_session.json"), session_info)
        _write_session_payload(_session_path_for(params["batch_id"]), session_info)
        
        return {"status": "initiated", "message": "Dojo mission dispatched."}
    except Exception as e:
        logging.error(f"Dojo start failure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/marathon")
async def start_marathon(params: dict):
    """Launches the multi-agent marathon batch runner."""
    try:
        script_path = os.path.join(ROOT_DIR, "tools", "marathon_runner.py")
        
        session_info = {
            "status": "starting",
            "params": params,
            "timestamp": datetime.now().isoformat(),
            "type": "marathon"
        }
        os.makedirs(EVALS_DIR, exist_ok=True)
        with open(os.path.join(EVALS_DIR, "active_session.json"), "w", encoding="utf-8") as f:
            json.dump(session_info, f)

        proc = subprocess.Popen([PYTHON_EXE, script_path, json.dumps(params)])
        session_info["launcher_pid"] = proc.pid
        _write_session_payload(os.path.join(EVALS_DIR, "active_session.json"), session_info)
        
        return {"status": "initiated", "message": "Marathon dispatched."}
    except Exception as e:
        logging.error(f"Marathon start failure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/session")
async def get_active_session(batch_id: str = None):
    """Polls for live session telemetry."""
    active_path = _session_path_for(batch_id) if batch_id else os.path.join(EVALS_DIR, "active_session.json")
    if not os.path.exists(active_path):
        return {"active": False}

    try:
        with open(active_path, "r", encoding="utf-8") as f:
            session = json.load(f)

        if not batch_id and session.get("status") in {"stopped", "completed", "failed"}:
            _clear_active_session_file()
            return {"active": False, "session": session, "telemetry": {}}

        launcher_pid = session.get("launcher_pid") or session.get("controller_pid")
        if session.get("status") in {"running", "starting"} and launcher_pid and not _pid_is_running(launcher_pid):
            session = _mark_session_stopped(session, "Stale batch session cleared after process exit.")
            _clear_active_session_file()
            if session.get("batch_id"):
                _write_session_payload(_session_path_for(session["batch_id"]), session)
            return {"active": False, "session": session, "telemetry": {}}
        
        # If there's an active run, check its live telemetry
        batch_id = session.get("batch_id")
        run_id = session.get("current_run_id")
        
        telemetry = {}
        if run_id:
            tel_path = os.path.join(RUNS_DIR, run_id, "live_telemetry.json")
            if os.path.exists(tel_path):
                with open(tel_path, "r", encoding="utf-8") as f:
                    telemetry = json.load(f)

        return {
            "active": True,
            "session": session,
            "telemetry": telemetry
        }
    except Exception as e:
        return {"active": False, "error": str(e)}


@router.post("/stop")
async def stop_active_session():
    """Stop the active Dojo eval or marathon session."""
    active_path = os.path.join(EVALS_DIR, "active_session.json")
    if not os.path.exists(active_path):
        return {"status": "idle", "message": "No active Dojo session found."}

    with open(active_path, "r", encoding="utf-8") as f:
        session = json.load(f)

    batch_id = session.get("batch_id")
    marathon_id = session.get("marathon_id")
    pids = [
        session.get("launcher_pid"),
        session.get("controller_pid"),
    ]

    killed = any(_taskkill_pid(pid) for pid in pids if pid)
    if not killed:
        killed = _kill_dojo_processes()

    stopped = _mark_session_stopped(session, "Batch stopped from Hub.")
    if batch_id:
        _write_session_payload(_session_path_for(batch_id), stopped)
    if marathon_id:
        _write_session_payload(_session_path_for(marathon_id), stopped)
    _clear_active_session_file()

    return {
        "status": "stopped",
        "batch_id": batch_id,
        "marathon_id": marathon_id,
        "killed": bool(killed),
        "message": "Active Dojo batch stopped.",
    }

@router.get("/batch/{batch_id:path}")
async def get_batch_results(batch_id: str):
    """Fetches result summary for a specific batch."""
    batch_path = os.path.join(BATCHES_DIR, batch_id, "batch_summary.json")
    if not os.path.exists(batch_path):
        raise HTTPException(status_code=404, detail="Batch results not found.")
    
    with open(batch_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # BACKWARD COMPATIBILITY: If 'runs' is missing but 'run_ids' exists,
    # try to load minimal data for each run from vault/evals/runs/
    if "runs" not in data and "run_ids" in data:
        data["runs"] = []
        for r_id in data["run_ids"]:
            run_meta_path = os.path.join(RUNS_DIR, r_id, "metadata.json")
            if os.path.exists(run_meta_path):
                try:
                    with open(run_meta_path, 'r', encoding='utf-8') as rf:
                        rmeta = json.load(rf)
                        raw_status = rmeta.get("status", "FAIL")
                        normalized_status = "PASS" if raw_status.lower() == "success" else raw_status.upper()
                        data["runs"].append({
                            "run_id": r_id,
                            "scenario_id": rmeta.get("scenario_id", "Unknown"),
                            "pass_fail": normalized_status,
                            "verdict": rmeta.get("classification", "FAIL")
                        })
                except: pass
    return data

@router.get("/history")
async def get_history():
    """Returns the last 10 batches."""
    if not os.path.exists(BATCHES_DIR):
        return []
    
    batches = []
    # Find all batch_summary.json files recursively
    import glob
    summary_files = glob.glob(os.path.join(BATCHES_DIR, "**", "batch_summary.json"), recursive=True)
    
    # Sort by creation time
    summary_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
    
    for summary_path in summary_files[:10]:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Map back the relative path as the batch_id
                b_id = os.path.relpath(os.path.dirname(summary_path), BATCHES_DIR).replace("\\", "/")
                batches.append({
                    "batch_id": b_id,
                    "target_agent": data.get("target_agent"),
                    "scenario_pack": data.get("scenario_pack"),
                    "average_score": data.get("average_score"),
                    "verdict": data.get("verdict"),
                    "timestamp": data.get("timestamp", datetime.now().isoformat())
                })
        except Exception:
            continue
    return batches

@router.get("/health")
async def get_health():
    """Checks status of critical Dojo dependencies."""
    import socket
    import httpx
    
    results = {
        "bridge": {"status": "ok", "message": "Neural Link active"},
        "demo_server": {"status": "unknown", "message": "Checking..."},
        "ollama": {"status": "unknown", "message": "Checking..."}
    }

    # 1. Check Demo Server (Port 3000)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", 3000)) == 0:
                results["demo_server"] = {"status": "ok", "message": "Online (Port 3000)"}
            else:
                results["demo_server"] = {"status": "error", "message": "Offline (Need launch_dojo.bat)"}
    except:
        results["demo_server"] = {"status": "error", "message": "Ping failed"}

    # 2. Check Ollama (Port 11434)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:11434/api/tags", timeout=1)
            if resp.status_code == 200:
                results["ollama"] = {"status": "ok", "message": "Ready (Local Inference)"}
            else:
                results["ollama"] = {"status": "error", "message": "Service Unresponsive"}
    except:
        results["ollama"] = {"status": "error", "message": "Offline (Ollama not running)"}

    return results
