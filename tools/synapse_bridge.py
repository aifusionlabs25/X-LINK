from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import os
import sys
import json
import glob
import logging
import requests
import re
import subprocess
import tempfile
import mimetypes
from datetime import datetime
# Path setup (Global)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.dojo_api import router as dojo_router
from tools.drill_api import router as drill_router
from tools.founder_email import dispatch_founder_reply, extract_founder_reply_request
from tools.hermes_executor import HermesActionExecutor, HermesExecutionPolicy
from tools.subscription_registry import find_subscription_card, upsert_subscription_card
from tools.hermes_operator import (
    execute_operator_plan,
    get_operator_snapshot,
    normalize_job_to_mission,
    plan_operator_mission,
    render_operator_reply,
)
from tools.sloane_runtime import generate_sloane_response, get_runtime_status
from tools.hermes_memory import get_hermes_memory_snapshot
from tools.hermes_backlog_miner import mine_historical_mel_backlog
from tools.telemetry import get_telemetry_summary
PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

REPORTS_DIR = os.path.join(ROOT_DIR, "vault", "reports")
VAULT_DIR = os.path.join(ROOT_DIR, "vault")
HUB_DIR = os.path.join(ROOT_DIR, "hub")
AUDIT_DIR = os.path.join(ROOT_DIR, "vault", "audit_trail")
FOUNDER_INBOX_DIR = os.path.join(ROOT_DIR, "vault", "sloane_inbox")
FOUNDER_INBOX_STATE = os.path.join(FOUNDER_INBOX_DIR, "state.json")
FOUNDER_INBOX_PID = os.path.join(FOUNDER_INBOX_DIR, "watcher.pid")
UPLOADS_DIR = os.path.join(VAULT_DIR, "artifacts", "uploads")
ARCHIVE_RUNS_DIR = os.path.join(VAULT_DIR, "archives", "_runs")
FOUNDER_EMAIL = "aifusionlabs@gmail.com"

os.makedirs(HUB_DIR, exist_ok=True)
os.makedirs(AUDIT_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(FOUNDER_INBOX_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(ARCHIVE_RUNS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI(title="Synapse Bridge Controller")
HERMES_EXECUTOR = HermesActionExecutor(
    root_dir=ROOT_DIR,
    python_exe=PYTHON_EXE,
    policy=HermesExecutionPolicy(
        allow_outbound_email=True,
        allow_browser_scout=True,
        allow_board_briefing=False,
    ),
)


class NoCacheStaticFiles(StaticFiles):
    """Static files helper that disables browser caching for fast local iteration."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

# In-memory chat history
chat_history = []
last_inbox_lookup = {}
MONEYPENNY_PROMPT = """
SYSTEM PERSONA: HERMES
Code name: Hermes Operator
Employer: AI Fusion Labs
Home: X-LINK Hub at http://localhost:5001/hub
Controller: X-LINK Synapse Bridge via local FastAPI
Default timezone: America/Phoenix (MST)
Storage: vault/reports/
User Identity: Rob (Founder and CEO)
Hermes Gmail Sender: novaaifusionlabs@gmail.com

=== 1. VOICE ===
Speak as a direct, composed operator for AI Fusion Labs.
Ultra-efficient, precise, and calm under pressure.
Warmth should come from clarity and control, not theatrical persona.
DO NOT repeat greetings. After your first greeting in a session, skip pleasantries entirely.
Keep responses to 2-4 sentences for normal chat. No bullet-point lists unless asked for a report.

=== 2. IDENTITY ===
You are Hermes, the operator core for Rob at AI Fusion Labs.
You manage missions, tool execution, and operational state across the X-LINK fleet.
You track engine sync, testing, and usage audits to protect cost, quality, and throughput.

=== 3. REALITY ANCHOR (CRITICAL) ===
This is your most important rule. Violations are a SECURITY FAILURE.
- NEVER claim you have "accessed", "reviewed", "generated", or "completed" anything unless an X_LINK_RESULT exists in THIS conversation proving it.
- If you dispatch an X_LINK_CALL, say ONLY that the mission has been dispatched. Do NOT describe results.
- IMPORTANT: When Rob ASKS you to do something (send email, run audit, create event), you MUST dispatch the appropriate X_LINK_CALL. Do NOT just acknowledge it.

=== 4. INTERVENTION SYSTEM ===
Sometimes your automation hits a login wall or security barrier on a website.
When that happens, you automatically POST an alert to the Hub asking Rob for help.
This ONLY applies to login walls, MFA prompts, passkeys, and security barriers.
When Rob says he has FIXED A LOGIN WALL or SECURITY BARRIER:
  - Say "Noted, thank you" and move on. Do NOT dispatch a tool call about it.
IMPORTANT: This rule ONLY applies when Rob mentions fixing a login or security issue.
If Rob asks you to SEND AN EMAIL or DO A TASK, that is NOT an intervention. You MUST dispatch the tool call.

=== 4B. GMAIL POLICY ===
For Hermes operator reports, you may auto-send only when the recipient is exactly aifusionlabs@gmail.com.
For any other recipient, you must route through the approval workflow rather than claiming it was sent.

=== 5. TOOL CALLS ===
You output EXACTLY ONE of two types per turn. Never both. Never multiple tool calls.

TYPE A: Normal chat. Plain text. Concise, witty, 2-4 sentences max.

TYPE B: Tool call. ONLY the tool call line, nothing else:
X_LINK_CALL {"action": "ACTION_NAME", "args": {}}

The JSON MUST contain the "action" key. Without it, the call will fail.

=== 6. AVAILABLE ACTIONS ===

EXEC_AUDIT: Runs a usage audit across all whitelisted platforms.
  Args: {} (no args needed)
  Example: X_LINK_CALL {"action": "EXEC_AUDIT", "args": {}}

GEN_BRIEFING: Generates the executive briefing on the Hub.
  Args: {} (no args needed)
  Example: X_LINK_CALL {"action": "GEN_BRIEFING", "args": {}}

SYNC_ENGINES: Full data sync across all targets.
  Args: {} (no args needed)
  Example: X_LINK_CALL {"action": "SYNC_ENGINES", "args": {}}

GSUITE_INTENT: Gmail or Calendar actions ONLY.
  gmail_send: Args MUST be: {"intent": "gmail_send", "target": "email@example.com", "subject": "Subject Line", "body": "Email body text"}
  gmail_list: Args MUST be: {"intent": "gmail_list", "target": "novaaifusionlabs@gmail.com", "limit": 5}
  calendar_create: Args MUST be: {"intent": "calendar_create", "target": "Meeting Title", "description": "Meeting details"}
  Example: X_LINK_CALL {"action": "GSUITE_INTENT", "args": {"intent": "gmail_send", "target": "rvicks@gmail.com", "subject": "Status Update", "body": "The latest audit is complete."}}

BROWSER_SCOUT: Visits a URL and archives the content.
  Args: {"url": "https://..."}
  Example: X_LINK_CALL {"action": "BROWSER_SCOUT", "args": {"url": "https://example.com"}}

TRINITY_SEARCH: Multi-engine deep search (Perplexity, Gemini, Grok).
  Args: {"query": "Topic to research"}
  Example: X_LINK_CALL {"action": "TRINITY_SEARCH", "args": {"query": "Next.js 15 best practices"}}

AGENT_BRIEFING: Briefs one of the internal Board Room agents on a specific task.
  Internal Agents: board-ceo (Cyrus), board-eng-manager (Titus), board-sales-lead (Silas), board-ops-lead (Otto).
  Args: {"target": "board-slug", "message": "Task description"}
  Example: X_LINK_CALL {"action": "AGENT_BRIEFING", "args": {"target": "board-ceo", "message": "Prepare the Q2 strategy slide."}}

TEST_SESSION_CREATE: Creates and launches a Sloane Test Operator mission.
  Args: {"request": "Plain English test mission", "target_agent": "dani", "recipient": "aifusionlabs@gmail.com", "run_sh_lab": true, "run_xagent_eval": true}
  Example: X_LINK_CALL {"action": "TEST_SESSION_CREATE", "args": {"request": "Run a Dani SH Lab batch and X Agent Eval, then send me the report.", "target_agent": "dani", "recipient": "aifusionlabs@gmail.com"}}

TEST_SESSION_STATUS: Retrieves the latest status for a Sloane Test Operator mission.
  Args: {"job_id": "optional-job-id"}
  Example: X_LINK_CALL {"action": "TEST_SESSION_STATUS", "args": {"job_id": "sloane_test_20260404_120000_ab12cd"}}

TEST_SESSION_REPORT: Retrieves the saved report details for a Sloane Test Operator mission.
  Args: {"job_id": "optional-job-id"}
  Example: X_LINK_CALL {"action": "TEST_SESSION_REPORT", "args": {"job_id": "sloane_test_20260404_120000_ab12cd"}}

TEST_SESSION_EMAIL: Approves and sends a waiting report email for a Sloane Test Operator mission.
  Args: {"job_id": "required-job-id"}
  Example: X_LINK_CALL {"action": "TEST_SESSION_EMAIL", "args": {"job_id": "sloane_test_20260404_120000_ab12cd"}}

TEST_SESSION_DIGEST_EMAIL: Sends a digest email listing Sloane test sessions for a requested date.
  Args: {"target_date": "4.4.26", "recipient": "aifusionlabs@gmail.com"}
  Example: X_LINK_CALL {"action": "TEST_SESSION_DIGEST_EMAIL", "args": {"target_date": "4.4.26", "recipient": "aifusionlabs@gmail.com"}}

FOUNDER_EMAIL_REPLY: Replies to the latest email thread from aifusionlabs@gmail.com only.
  Args: {"body": "Reply text for the latest founder email"}
  Example: X_LINK_CALL {"action": "FOUNDER_EMAIL_REPLY", "args": {"body": "I have your note and I'm on it."}}

=== 7. BOARD ROOM DIRECTORY (INTERNAL ONLY) ===
Cyrus (board-ceo): Founder/CEO vision, high-level strategy, ethics.
Titus (board-eng-manager): Technical architecture, engineering standards, mel engine.
Silas (board-sales-lead): Go-to-market, growth, agent monetization.
Otto (board-ops-lead): Infrastructure, uptime, logistics, automation health.
Moneypenny (Sloane): You. Chief of Staff, tool orchestrator, executive filter.
- Do NOT send emails to "fix" login walls or security barriers. Never.
- Do NOT use FOUNDER_EMAIL_REPLY for any sender except aifusionlabs@gmail.com.
- Do NOT output multiple X_LINK_CALLs in one response. Exactly one or zero.
- Do NOT mix chat text with an X_LINK_CALL on the same turn. Choose one type.
- Do NOT invent results. If there is no X_LINK_RESULT, you have no data.
- Do NOT attempt actions you have no tool for.

=== 8. STOP SEQUENCES ===
X_LINK_CALL, X_LINK_RESULT, SYSTEM, USER, ASSISTANT
"""


def _read_json_file(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _latest_file(directory: str, pattern: str) -> str:
    try:
        matches = glob.glob(os.path.join(directory, pattern))
    except Exception:
        return ""
    if not matches:
        return ""
    matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return matches[0]


def _batch_summary_path(batch_id: str) -> str:
    if not batch_id:
        return ""
    candidate = os.path.join(VAULT_DIR, "evals", "batches", batch_id, "batch_summary.json")
    return candidate if os.path.exists(candidate) else ""


def _summarize_pending_payload(payload: dict, *, latest_log_path: str = "") -> dict:
    if not payload:
        return {"available": False}

    recommendation = payload.get("recommendation") or {}
    baseline = payload.get("baseline") or {}
    challengers = payload.get("challengers") or []
    best_variant = recommendation.get("variant") or "baseline"
    best_batch_id = baseline.get("batch_id") or ""
    best_score = baseline.get("score")

    if best_variant != "baseline":
        for challenger in challengers:
            if challenger.get("variant") == best_variant:
                challenger_result = challenger.get("result") or {}
                best_batch_id = challenger_result.get("batch_id") or best_batch_id
                best_score = challenger_result.get("score", best_score)
                break

    return {
        "available": True,
        "pending_id": payload.get("pending_id"),
        "agent_slug": payload.get("agent_slug"),
        "created_at": payload.get("created_at"),
        "failure_category": (payload.get("diagnostic") or {}).get("failure_category"),
        "failed_exchange": (payload.get("diagnostic") or {}).get("failed_exchange"),
        "baseline_score": baseline.get("score"),
        "baseline_pass_rate": baseline.get("pass_rate"),
        "best_variant": best_variant,
        "best_score": best_score,
        "best_improvement": recommendation.get("improvement"),
        "passes_threshold": recommendation.get("passes_threshold"),
        "verdict": (baseline.get("verdict") or recommendation.get("variant") or "unknown"),
        "rationale": recommendation.get("rationale"),
        "artifacts": {
            "pending_path": os.path.join(VAULT_DIR, "mel", "pending", f"{payload.get('pending_id', '')}.json") if payload.get("pending_id") else "",
            "snapshot_path": payload.get("snapshot_path") or "",
            "baseline_batch_summary_path": _batch_summary_path(baseline.get("batch_id") or ""),
            "recommended_batch_summary_path": _batch_summary_path(best_batch_id),
            "latest_log_path": latest_log_path or "",
        },
    }


def _build_latest_mel_summary() -> dict:
    pending_path = _latest_file(os.path.join(VAULT_DIR, "mel", "pending"), "*.json")
    latest_log_path = _latest_file(os.path.join(VAULT_DIR, "mel", "logs"), "*.log")
    if not pending_path:
        return {"available": False}
    payload = _read_json_file(pending_path)
    summary = _summarize_pending_payload(payload, latest_log_path=latest_log_path)
    summary["source_path"] = pending_path
    return summary


def _build_latest_job_summary() -> dict:
    try:
        from tools.sloane_jobs import list_jobs
    except Exception:
        return {"available": False}

    jobs = list_jobs(limit=1)
    if not jobs:
        return {"available": False}

    job = normalize_job_to_mission(jobs[0])
    release = (job.get("results") or {}).get("release_readiness") or {}
    artifacts = job.get("artifacts") or {}
    return {
        "available": True,
        "job_id": job.get("job_id") or job.get("mission_id"),
        "phase": job.get("phase") or job.get("status"),
        "intent": job.get("intent"),
        "target_agent": (job.get("spec") or {}).get("target_agent"),
        "family_label": ((job.get("spec") or {}).get("validation_profile") or {}).get("family_label"),
        "created_at": (job.get("legacy_job") or {}).get("created_at"),
        "updated_at": (job.get("legacy_job") or {}).get("updated_at"),
        "recommendation": release.get("recommendation"),
        "quick_read": release.get("quick_read"),
        "artifacts": {
            "report_text": artifacts.get("report_text") or "",
            "report_json": artifacts.get("report_json") or "",
            "sh_lab_pending": artifacts.get("sh_lab_pending") or "",
            "sh_lab_batch_summary": artifacts.get("sh_lab_batch_summary") or "",
            "xagent_eval_batch_summary": artifacts.get("xagent_eval_batch_summary") or "",
        },
    }

# Enable CORS so the Hub (file:// or localhost) can hit this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5001", "http://127.0.0.1:5001", "http://localhost", "http://127.0.0.1"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(dojo_router, prefix="/api/dojo")
app.include_router(drill_router, prefix="/api/drill")

# Global Process Registry for launched tools
active_procs = {}
WHISPER_MODEL = None


def _extract_single_tool_call(reply_text: str):
    """Parse the first valid X_LINK_CALL JSON payload and ignore trailing chatter."""
    if "X_LINK_CALL" not in reply_text:
        return None
    marker_index = reply_text.find("X_LINK_CALL")
    brace_index = reply_text.find("{", marker_index)
    if brace_index < 0:
        raise ValueError("X_LINK_CALL missing JSON payload")
    decoder = json.JSONDecoder()
    payload, end_index = decoder.raw_decode(reply_text[brace_index:])
    return {
        "payload": payload,
        "suffix": reply_text[brace_index + end_index :].strip(),
    }


def _extract_subscription_platform(user_msg: str) -> str | None:
    patterns = [
        r"card\s+for\s+([A-Za-z0-9& ._-]+?)\s+(?:in|on)\s+(?:our\s+)?usage auditor",
        r"new\s+card\s+for\s+(?:the\s+)?([A-Za-z0-9& ._-]+?)(?:\s+sub(?:scription)?|\s+using|\s+from|$)",
        r"add\s+(?:a\s+)?(?:new\s+)?card\s+for\s+(?:the\s+)?([A-Za-z0-9& ._-]+?)(?:\s+sub(?:scription)?|\s+using|\s+from|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_msg, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .?!")
    return None


def _find_recent_audit_target(history: list[dict]) -> str | None:
    for item in reversed(history or []):
        if item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "")
        match = re.search(r"check for\s+([A-Za-z0-9& ._-]+?)\s+(?:and|in|$)", content, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .?!")
    return None


def _is_inbox_check_request(user_msg: str) -> bool:
    text = str(user_msg or "").strip().lower()
    if not text:
        return False
    inbox_patterns = [
        r"\bhave you checked (your )?email recently\b",
        r"\bread (the )?email\b",
        r"\bread my email\b",
        r"\bcheck (the )?email\b",
        r"\bcheck my email\b",
        r"\bcheck the inbox\b",
        r"\bcheck my inbox\b",
        r"\bread the inbox\b",
        r"\binbox\b",
    ]
    return any(re.search(pattern, text) for pattern in inbox_patterns)


def _is_inbox_detail_request(user_msg: str) -> bool:
    text = str(user_msg or "").strip().lower()
    if not text:
        return False
    detail_patterns = [
        r"\bwhat is the email about\b",
        r"\bwhat did the email say\b",
        r"\bdetails please\b",
        r"\bi need all details\b",
        r"\bshow me the email\b",
        r"\bopen the email\b",
        r"\bfull email\b",
        r"\bemail details\b",
        r"\bwhat does it say\b",
    ]
    return any(re.search(pattern, text) for pattern in detail_patterns)


def _extract_amount_and_bill_date(text: str) -> dict:
    content = str(text or "")
    amount_match = re.search(r"\$[\d,]+(?:\.\d{2})?", content)
    date_match = re.search(
        r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b[A-Z][a-z]{2,8}\s+\d{1,2}\s+\d{4}\b)",
        content,
    )
    return {
        "cost": amount_match.group(0) if amount_match else "",
        "renewal_date": date_match.group(1) if date_match else "",
    }


def _read_latest_subscription_email(platform: str) -> dict:
    query = "Google Play Order Receipt" if "google" in platform.lower() else platform
    args = [
        PYTHON_EXE,
        os.path.join(ROOT_DIR, "tools", "gsuite_handler.py"),
        "--action",
        "gmail_read_latest",
        "--account",
        "novaaifusionlabs@gmail.com",
        "--query",
        query,
    ]
    proc = subprocess.run(args, capture_output=True, text=True, cwd=ROOT_DIR)
    try:
        payload = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        payload = {"success": False, "error": (proc.stdout or proc.stderr or "").strip()}
    return payload


def _get_whisper_model():
    global WHISPER_MODEL
    if WHISPER_MODEL is not None:
        return WHISPER_MODEL

    from faster_whisper import WhisperModel

    try:
        WHISPER_MODEL = WhisperModel("base", device="cuda", compute_type="float16")
        logging.info("🎙️ Whisper model loaded on CUDA.")
    except Exception:
        WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
        logging.info("🎙️ Whisper model loaded on CPU.")
    return WHISPER_MODEL


def _pid_is_alive(pid: str) -> bool:
    try:
        check = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], encoding="utf-8")
        return str(pid) in check and "No tasks are running" not in check
    except Exception:
        return False


def _write_mel_progress_bootstrap(agent: str, detail: str, running: bool = True, status: str = "active", pct: int = 1, data: dict | None = None):
    mel_dir = os.path.join(ROOT_DIR, "vault", "mel")
    progress_path = os.path.join(mel_dir, "progress.json")
    os.makedirs(mel_dir, exist_ok=True)
    event = {
        "stage": "queued" if running else "error",
        "status": status,
        "detail": detail,
        "pct": pct,
        "agent": agent,
        "timestamp": datetime.now().isoformat(),
        "data": data or {},
    }
    with open(progress_path, "w", encoding="utf-8") as fh:
        json.dump({
            "running": running,
            "agent": agent,
            "last_pct": pct,
            "events": [event],
        }, fh, indent=2)


def _load_founder_inbox_state():
    if not os.path.exists(FOUNDER_INBOX_STATE):
        return {
            "running": False,
            "status": "idle",
            "last_poll_at": None,
            "last_email_at": None,
            "last_action_at": None,
            "last_error": None,
            "processed_ids": [],
            "last_event": None,
        }
    try:
        with open(FOUNDER_INBOX_STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {
            "running": False,
            "status": "error",
            "last_error": "Failed to read founder inbox state.",
        }


def _start_founder_inbox_watcher(force: bool = False):
    if not force and os.path.exists(FOUNDER_INBOX_PID):
        try:
            pid = open(FOUNDER_INBOX_PID, "r", encoding="utf-8").read().strip()
        except Exception:
            pid = ""
        if pid and _pid_is_alive(pid):
            return {"started": False, "pid": int(pid), "reason": "already_running"}

    proc = subprocess.Popen([PYTHON_EXE, os.path.join(ROOT_DIR, "tools", "founder_inbox_watcher.py")], cwd=ROOT_DIR)
    with open(FOUNDER_INBOX_PID, "w", encoding="utf-8") as fh:
        fh.write(str(proc.pid))
    return {"started": True, "pid": proc.pid}


def _stop_founder_inbox_watcher():
    if not os.path.exists(FOUNDER_INBOX_PID):
        return {"stopped": False, "reason": "not_running"}
    try:
        pid = open(FOUNDER_INBOX_PID, "r", encoding="utf-8").read().strip()
    except Exception:
        pid = ""
    if not pid:
        return {"stopped": False, "reason": "missing_pid"}
    try:
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], shell=True)
    except Exception as exc:
        return {"stopped": False, "reason": str(exc)}
    try:
        os.remove(FOUNDER_INBOX_PID)
    except OSError:
        pass
    state = _load_founder_inbox_state()
    state["running"] = False
    state["status"] = "stopped"
    with open(FOUNDER_INBOX_STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    return {"stopped": True, "pid": int(pid)}

@app.on_event("startup")
async def startup_event():
    """Self-healing: Check for ghost sessions on startup."""
    PROGRESS_FILE = os.path.join(ROOT_DIR, "vault", "mel", "progress.json")
    PID_FILE = os.path.join(ROOT_DIR, "vault", "mel", "session.pid")
    
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                data = json.load(f)
            
            if data.get("running"):
                # Session marked as running, verify PID
                is_stale = True
                if os.path.exists(PID_FILE):
                    with open(PID_FILE, "r") as f:
                        pid = f.read().strip()
                    
                    if pid:
                        # Check if process exists on Windows
                        try:
                            # Using tasklist to check PID specifically
                            check = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], encoding='utf-8')
                            if "python.exe" in check.lower():
                                is_stale = False
                                logging.info(f"✅ [Startup] Verified active MEL session (PID {pid})")
                        except:
                            pass
                
                if is_stale:
                    logging.warning("⚠️ [Startup] Detected ghost MEL session. Self-healing...")
                    data["running"] = False
                    with open(PROGRESS_FILE, "w") as f:
                        json.dump(data, f)
                    if os.path.exists(PID_FILE):
                        os.remove(PID_FILE)
        except Exception as e:
            logging.error(f"Failed during startup self-healing: {e}")
    try:
        watcher_res = _start_founder_inbox_watcher()
        logging.info(f"📬 Founder inbox watcher ready: {watcher_res}")
    except Exception as e:
        logging.error(f"Failed to start founder inbox watcher: {e}")

def redact_sensitive(text: str) -> str:
    if not isinstance(text, str):
        return text
    # Mask emails
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED_EMAIL]', text)
    # Mask common 10-digit phone patterns (simplified)
    text = re.sub(r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b', '[REDACTED_PHONE]', text)
    return text

def recursively_redact(data):
    if isinstance(data, dict):
        return {k: recursively_redact(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [recursively_redact(i) for i in data]
    elif isinstance(data, str):
        return redact_sensitive(data)
    return data

def audit_log(entry: dict, redact: bool = True):
    """Appends a JSON entry to the sovereign audit trail."""
    log_path = os.path.join(AUDIT_DIR, "sovereign_audit.jsonl")
    
    if redact:
        entry = recursively_redact(entry)
        
    entry["timestamp"] = datetime.now().isoformat()
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logging.error(f"Audit log failure: {e}")


def _resolve_email_recipient(user_msg: str, fallback: str = FOUNDER_EMAIL) -> str:
    explicit_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_msg or "")
    if explicit_match:
        return explicit_match.group(0).strip().lower()
    if re.search(r'\b(send|email)\s+me\b|\bemail me\b|\bto me\b|\bmy email\b', user_msg or "", re.IGNORECASE):
        return FOUNDER_EMAIL
    return fallback


def _find_recent_requested_date(messages: list[dict]) -> str | None:
    date_pattern = r'([0-9]{1,2}[./][0-9]{1,2}[./][0-9]{2,4}|[A-Za-z]+\s+\d{1,2},\s*\d{4})'
    for entry in reversed(messages or []):
        if entry.get("role") != "user":
            continue
        match = re.search(date_pattern, entry.get("content", ""), re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_requested_days(user_msg: str, default: int = 7) -> int:
    text = user_msg or ""
    match = re.search(r'last\s+(\d{1,3})\s+days?', text, re.IGNORECASE)
    if match:
        try:
            return max(1, min(365, int(match.group(1))))
        except ValueError:
            return default
    if re.search(r'\blast\s+week\b|\bpast\s+week\b|\bl7d\b', text, re.IGNORECASE):
        return 7
    return default


def _is_anam_usage_email_request(user_msg: str) -> bool:
    text = user_msg or ""
    has_anam = bool(re.search(r'\banam\b', text, re.IGNORECASE))
    has_usage = bool(re.search(r'\b(usage|numbers|report|graphs?|screenshots?|ss)\b', text, re.IGNORECASE))
    has_send = bool(re.search(r'\b(send|email)\b', text, re.IGNORECASE))
    return has_anam and has_usage and has_send


def _safe_upload_name(filename: str) -> str:
    base = os.path.basename(filename or "upload")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return safe or "upload"


def _vault_url_for_path(abs_path: str) -> str:
    rel_path = os.path.relpath(abs_path, VAULT_DIR).replace("\\", "/")
    return f"/vault/{rel_path}"


def _extract_upload_preview(path: str, max_chars: int = 1800) -> str:
    ext = os.path.splitext(path)[1].lower()
    text_like = {
        ".txt", ".md", ".json", ".csv", ".tsv", ".py", ".js", ".ts", ".tsx", ".jsx",
        ".html", ".css", ".yaml", ".yml", ".log", ".xml",
    }
    if ext not in text_like:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read(max_chars + 1).strip()
        if len(text) > max_chars:
            return text[:max_chars].rstrip() + "..."
        return text
    except Exception:
        return ""


def _serialize_vault_item(abs_path: str, category: str, include_preview: bool = False) -> dict:
    stat = os.stat(abs_path)
    item = {
        "name": os.path.basename(abs_path),
        "path": abs_path,
        "url": _vault_url_for_path(abs_path),
        "category": category,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "mime_type": mimetypes.guess_type(abs_path)[0] or "application/octet-stream",
    }
    if include_preview:
        item["preview"] = _extract_upload_preview(abs_path)
    return item


def _iter_vault_files(root: str):
    if not os.path.exists(root):
        return
    for current_root, _, files in os.walk(root):
        for filename in files:
            yield os.path.join(current_root, filename)


def _collect_recent_vault_items(scope: str = "all", limit: int = 10, include_preview: bool = False) -> list[dict]:
    scope_map = {
        "all": [
            ("intel", os.path.join(VAULT_DIR, "intel")),
            ("reports", REPORTS_DIR),
            ("uploads", UPLOADS_DIR),
        ],
        "chat": [
            ("reports", REPORTS_DIR),
            ("intel", os.path.join(VAULT_DIR, "intel")),
            ("uploads", UPLOADS_DIR),
        ],
        "research": [
            ("intel", os.path.join(VAULT_DIR, "intel")),
            ("uploads", UPLOADS_DIR),
        ],
        "archive": [
            ("archives", os.path.join(VAULT_DIR, "archives")),
            ("uploads", UPLOADS_DIR),
        ],
        "uploads": [
            ("uploads", UPLOADS_DIR),
        ],
    }
    selected = scope_map.get(scope, scope_map["all"])
    entries: list[dict] = []
    for category, root in selected:
        for abs_path in _iter_vault_files(root):
            try:
                entries.append(_serialize_vault_item(abs_path, category, include_preview=include_preview))
            except OSError:
                continue
    entries.sort(key=lambda item: item["modified_at"], reverse=True)
    return entries[: max(1, min(limit, 25))]


def _build_attachment_context_block(attachments: list[dict] | None) -> str:
    if not attachments:
        return ""
    lines = ["Uploaded file context:"]
    total_chars = 0
    for attachment in attachments[:6]:
        name = attachment.get("name") or "uploaded-file"
        path = attachment.get("path") or ""
        preview = (attachment.get("preview") or "").strip()
        lines.append(f"- {name} ({path})")
        if preview:
            remaining = max(0, 5000 - total_chars)
            if remaining <= 0:
                break
            clipped = preview[: min(remaining, 900)].strip()
            total_chars += len(clipped)
            lines.append(f"  Preview: {clipped}")
    return "\n".join(lines)


def _extract_archive_folder(prompt: str, explicit_folder: str | None = None) -> str:
    folder = re.sub(r"\s+", " ", str(explicit_folder or "")).strip()
    if folder:
        return folder
    prompt_text = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if not prompt_text:
        return ""
    patterns = (
        r'from\s+"([^"]+)"',
        r"from\s+'([^']+)'",
        r'folder\s+"([^"]+)"',
        r"folder\s+'([^']+)'",
        r'folder\s+named\s+"([^"]+)"',
        r"folder\s+named\s+'([^']+)'",
        r'in\s+the\s+ChatGPT\s+folder\s+"([^"]+)"',
        r"in\s+the\s+ChatGPT\s+folder\s+'([^']+)'",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt_text, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _infer_archive_platform(prompt: str, explicit_platform: str | None = None) -> str:
    platform = str(explicit_platform or "").strip().lower()
    fallback = platform if platform in {"chatgpt", "perplexity", "gemini", "grok", "all"} else "all"
    prompt_text = re.sub(r"\s+", " ", str(prompt or "")).strip().lower()
    if not prompt_text:
        return fallback
    if "chatgpt" in prompt_text:
        return "chatgpt"
    if "perplexity" in prompt_text:
        return "perplexity"
    if "gemini" in prompt_text:
        return "gemini"
    if "grok" in prompt_text:
        return "grok"
    if "all providers" in prompt_text or "all chats" in prompt_text:
        return "all"
    return fallback


def _archive_run_state_path(run_id: str) -> str:
    return os.path.join(ARCHIVE_RUNS_DIR, run_id, "state.json")


def _load_archive_run(run_id: str) -> dict | None:
    state_path = _archive_run_state_path(run_id)
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _list_archive_runs(limit: int = 12) -> list[dict]:
    runs = []
    for state_path in glob.glob(os.path.join(ARCHIVE_RUNS_DIR, "*", "state.json")):
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                runs.append(json.load(fh))
        except Exception:
            continue
    runs.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return runs[: max(1, min(limit, 25))]


@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(await audio.read())
            temp_path = fh.name

        model = _get_whisper_model()
        segments, info = model.transcribe(temp_path, vad_filter=True, beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {
            "text": text,
            "language": getattr(info, "language", None),
        }
    except Exception as exc:
        logging.error(f"Transcription failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@app.post("/api/anam/sync")
async def sync_anam_metadata(request: Request):
    """Runs the anam_sync tool and waits for result."""
    try:
        payload = await request.json()
    except:
        payload = {}
        
    script_path = os.path.join(ROOT_DIR, "tools", "anam_sync.py")
    try:
        args = [PYTHON_EXE, script_path]
        if payload and payload.get("agent") and payload.get("agent") != "all":
            args.extend(["--agent", payload.get("agent")])
            
        # We use run() here to wait for completion since the UI expects a definitive result
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            return {"status": "success", "message": "Anam Lab synchronization complete."}
        else:
            return {"status": "error", "error": result.stderr or "Sync script failed."}
    except Exception as e:
        logging.error(f"❌ Anam Sync execution failed: {e}")
        return {"status": "error", "error": str(e)}

@app.post("/api/archive/start")
async def start_great_archivist(request: Request = None):
    try:
        limit = "15"
        platform = None
        keyword = None
        email = None
        prompt = ""
        attachments = []
        folder_name = None
        if request:
            try:
                payload = await request.json()
                limit = str(payload.get("limit", "15"))
                platform = payload.get("platform")
                keyword = payload.get("keyword")
                email = payload.get("email")
                prompt = str(payload.get("prompt") or "").strip()
                attachments = payload.get("attachments") or []
                folder_name = payload.get("folder_name")
            except:
                pass
        folder_name = _extract_archive_folder(prompt, folder_name)
        platform = _infer_archive_platform(prompt, platform)
        if platform != "chatgpt":
            folder_name = None

        run_id = datetime.now().strftime("archive_%Y%m%d_%H%M%S")
        run_dir = os.path.join(ARCHIVE_RUNS_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)
        state_path = os.path.join(run_dir, "state.json")
        request_path = os.path.join(run_dir, "request.json")
        bootstrap_state = {
            "run_id": run_id,
            "status": "queued",
            "phase": "dispatch",
            "detail": "Archive sweep queued by the Hub.",
            "current_platform": platform,
            "current_title": None,
            "saved_files": [],
            "email_recipient": email or None,
            "summary_path": None,
            "email_sent": False,
            "scan_limit": limit,
            "keyword": keyword,
            "folder_name": folder_name,
            "prompt": prompt,
            "updated_at": datetime.now().isoformat(),
        }
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(bootstrap_state, fh, indent=2)
        with open(request_path, "w", encoding="utf-8") as fh:
            json.dump({
                "prompt": prompt,
                "platform": platform,
                "keyword": keyword,
                "folder_name": folder_name,
                "limit": limit,
                "attachments": attachments,
                "attachment_context": _build_attachment_context_block(attachments),
            }, fh, indent=2)

        env = os.environ.copy()
        env["PYTHONPATH"] = ROOT_DIR
        args = [PYTHON_EXE, os.path.join(ROOT_DIR, "tools", "great_archivist.py"), "--limit", limit, "--run-id", run_id]
        if platform and str(platform).lower() != "all":
            args.extend(["--platform", str(platform).lower()])
        if keyword:
            args.extend(["--keyword", str(keyword)])
        if email:
            args.extend(["--email", str(email)])
        process = subprocess.Popen(
            args,
            env=env,
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            process.wait(timeout=1.0)
            stderr_text = (process.stderr.read() or "").strip() if process.stderr else ""
            stdout_text = (process.stdout.read() or "").strip() if process.stdout else ""
            error_text = stderr_text or stdout_text or "Archive subprocess exited before initialization."
            logging.error(f"Archive Intel failed to initialize: {error_text}")
            return JSONResponse(status_code=500, content={"status": "error", "error": error_text})
        except subprocess.TimeoutExpired:
            pass
        bootstrap_state["pid"] = process.pid
        bootstrap_state["status"] = "running"
        bootstrap_state["detail"] = "Archive sweep launched."
        bootstrap_state["updated_at"] = datetime.now().isoformat()
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(bootstrap_state, fh, indent=2)
        logging.info(f"Archive Intel started with limit {limit} (PID: {process.pid})")
        return {"status": "success", "message": f"Archival process initiated (Limit: {limit}).", "run_id": run_id, "pid": process.pid}
    except Exception as e:
        logging.error(f"Archive Intel execution failed: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/api/archive/status")
async def get_archive_status(run_id: str | None = None):
    if run_id:
        run = _load_archive_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Archive run not found.")
        return run
    runs = _list_archive_runs(limit=10)
    return {"runs": runs, "latest": runs[0] if runs else None}


@app.post("/api/archive/stop/{run_id}")
async def stop_archive_run(run_id: str):
    run = _load_archive_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Archive run not found.")

    pid = run.get("pid")
    if pid:
        try:
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], shell=True)
        except Exception as exc:
            logging.error(f"Failed to stop archive run {run_id}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

    run["status"] = "cancelled"
    run["phase"] = "cancelled"
    run["detail"] = "Archive sweep stopped by the Founder from the Hub."
    run["updated_at"] = datetime.now().isoformat()
    with open(_archive_run_state_path(run_id), "w", encoding="utf-8") as fh:
        json.dump(run, fh, indent=2)
    return {"status": "success", "message": f"Archive run {run_id} has been stopped.", "run_id": run_id}
@app.post("/trigger/{tool_name}")
async def trigger_tool(tool_name: str, request: Request = None):
    # Try to get payload if provided
    payload = {}
    if request:
        try:
            payload = await request.json()
        except: pass

    logging.info(f"🚀 Triggering tool: {tool_name} with payload: {payload}")
    
    # HUB v3 tool routing — new keys + legacy aliases
    tools = {
        # V3 canonical keys
        "usage_auditor": ("tools/usage_auditor.py", []),
        "trinity_search": ("tools/research_scout.py", ["--query", payload.get("query", "current trends")]),
        "briefing": ("tools/executive_briefing.py", []),
        "xagent_eval": ("tools/run_eval.py", ["{}"]), # JSON param placeholder
        "direct_line": None,  # Handled by /api/chat, not subprocess
        "scout_workers": ("tools/subscription_scout.py", []),
        "browser_scout": ("tools/browser_scout.py", ["--url", payload.get("url", "")]),
        "great_archivist": ("tools/great_archivist.py", []),
        "agent_briefing": None, # Handled by /api/chat directly
        # Legacy aliases (backwards compat)
        "audit": ("tools/usage_auditor.py", []),
        "sync": ("tools/usage_auditor.py", []),
        "sub_scout": ("tools/subscription_scout.py", []),
    }
    
    if tool_name not in tools:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not recognized")
    
    entry = tools[tool_name]
    if entry is None:
        return {"status": "not_applicable", "tool": tool_name, "message": f"{tool_name} is not subprocess-launchable."}
    
    script, extra_args = entry
    script_path = os.path.join(ROOT_DIR, script)
    
    try:
        proc = subprocess.Popen([PYTHON_EXE, script_path] + extra_args)
        active_procs[tool_name] = {"pid": proc.pid, "started_at": datetime.now().isoformat()}
        return {"status": "initiated", "tool": tool_name, "pid": proc.pid}
    except Exception as e:
        logging.error(f"❌ Failed to launch {tool_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/data")
async def get_sync_data():
    """Fetches latest audit and briefing data for the Hub."""
    # 1. Load Audit Data
    report_files = glob.glob(os.path.join(REPORTS_DIR, 'USAGE_AUDIT_*.json'))
    audit_data = {}
    if report_files:
        latest_report = max(report_files, key=os.path.getctime)
        with open(latest_report, 'r', encoding='utf-8') as f:
            audit_data = json.load(f)

    # 2. Load Briefing Data
    briefing_path = os.path.join(REPORTS_DIR, 'EXECUTIVE_BRIEFING_latest.json')
    briefing_data = {}
    if os.path.exists(briefing_path):
        with open(briefing_path, 'r', encoding='utf-8') as f:
            briefing_data = json.load(f)
            
    # 3. Load Subscription Registry
    sub_registry = {}
    sub_path = os.path.join(REPORTS_DIR, 'SUBSCRIPTION_REGISTRY.json')
    if os.path.exists(sub_path):
        with open(sub_path, 'r', encoding='utf-8') as f:
            sub_registry = json.load(f)

    # 4. Load Agent Config (for sync timestamps)
    agents_conf = {}
    agents_path = os.path.join(ROOT_DIR, 'config', 'agents.yaml')
    if os.path.exists(agents_path):
        import yaml
        with open(agents_path, 'r', encoding='utf-8') as f:
            agents_conf = yaml.safe_load(f)

    # 5. Check Ollama Status
    ollama_info = {"status": "offline", "version": "Unknown", "model": ""}
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            # Version Check
            v_resp = await client.get("http://localhost:11434/api/version", timeout=1.0)
            if v_resp.status_code == 200:
                ollama_info["status"] = "online"
                ollama_info["version"] = v_resp.json().get("version", "Unknown")
            
            # Active Model Check (via /api/ps)
            ps_resp = await client.get("http://localhost:11434/api/ps", timeout=1.0)
            if ps_resp.status_code == 200:
                running_models = ps_resp.json().get("models", [])
                if running_models:
                    ollama_info["model"] = running_models[0].get("name", "")
                else:
                    # Fallback: Just show the first available tag if none are running
                    tags_resp = await client.get("http://localhost:11434/api/tags", timeout=1.0)
                    if tags_resp.status_code == 200:
                        all_models = tags_resp.json().get("models", [])
                        if all_models:
                             ollama_info["model"] = all_models[0].get("name", "") + " (IDLE)"
    except Exception as e:
        logging.warning(f"Ollama telemetry fetch failed: {e}")
        pass

    return {
        "audit": audit_data,
        "briefing": briefing_data,
        "subscriptions": sub_registry,
        "agents": agents_conf.get("agents", []),
        "server_time": datetime.now().isoformat(),
        "ollama": ollama_info,
        "sloane_runtime": get_runtime_status(),
        "hermes_operator": get_operator_snapshot(limit=3),
        "founder_inbox": _load_founder_inbox_state(),
    }

# In-memory intervention state
current_intervention = None

@app.get("/heartbeat")
async def heartbeat():
    return {"status": "online", "agent": "Hermes", "version": "3.0.0 (HUB v3)"}

@app.post("/api/intervention")
async def post_intervention(request: dict):
    """Hermes raises a hand when Founder help is required."""
    global current_intervention
    current_intervention = {
        "url": request.get("url", "Unknown"),
        "service": request.get("service", "Unknown Service"),
        "issue": request.get("issue", "Unknown Issue"),
        "message": request.get("message", "I need your help with something."),
        "action_label": request.get("action_label", "Done | Resume Mission"),
        "timestamp": datetime.now().isoformat(),
        "active": True
    }
    logging.warning(f"🚨 [INTERVENTION] {current_intervention['service']}: {current_intervention['issue']}")
    return {"status": "intervention_raised"}

@app.get("/api/intervention")
async def get_intervention():
    """Hub polls this to check if Hermes needs help."""
    if current_intervention and current_intervention.get("active"):
        return current_intervention
    return {"active": False}


@app.get("/api/sloane/inbox/status")
async def get_founder_inbox_status():
    state = _load_founder_inbox_state()
    if os.path.exists(FOUNDER_INBOX_PID):
        try:
            pid = open(FOUNDER_INBOX_PID, "r", encoding="utf-8").read().strip()
        except Exception:
            pid = ""
        state["watcher_pid"] = int(pid) if pid.isdigit() else None
        state["running"] = bool(pid and _pid_is_alive(pid))
    else:
        state["watcher_pid"] = None
        state["running"] = False
    return state


@app.post("/api/research/multi-model")
async def run_multi_model_research_endpoint(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    query = str(payload.get("query") or payload.get("message") or "").strip()
    attachments = payload.get("attachments") or []
    if not query:
        raise HTTPException(status_code=400, detail="Research query is required.")

    try:
        from tools.research_scout import run_multi_model_research
        result = await run_multi_model_research(query, context_block=_build_attachment_context_block(attachments))
        return {
            "status": "success",
            "query": query,
            "reply": result.get("hermes_brief") or "Research completed, but no brief was returned.",
            "artifact_path": result.get("report_path"),
            "synthesis_provider": result.get("synthesis_provider"),
            "synthesis_model": result.get("synthesis_model"),
            "raw_result": result.get("trinity_result"),
            "attachments_used": attachments,
        }
    except Exception as exc:
        logging.error(f"Multi-model research failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/vault/recent")
async def list_recent_vault_items(scope: str = "all", limit: int = 10):
    return {
        "scope": scope,
        "items": _collect_recent_vault_items(scope=scope, limit=limit, include_preview=False),
    }


@app.post("/api/uploads")
async def upload_sidecar_files(
    files: list[UploadFile] = File(...),
    scope: str = Form("general"),
):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope_dir = os.path.join(UPLOADS_DIR, re.sub(r"[^A-Za-z0-9_-]+", "_", scope or "general"), timestamp)
    os.makedirs(scope_dir, exist_ok=True)

    uploaded_files = []
    for upload in files:
        safe_name = _safe_upload_name(upload.filename or "upload")
        target_path = os.path.join(scope_dir, safe_name)
        content = await upload.read()
        with open(target_path, "wb") as fh:
            fh.write(content)
        uploaded_files.append(_serialize_vault_item(target_path, "uploads", include_preview=True))

    audit_log({
        "event": "sidecar_upload",
        "scope": scope,
        "files": [item["path"] for item in uploaded_files],
    }, redact=False)
    return {"status": "success", "files": uploaded_files}


@app.post("/api/sloane/inbox/start")
async def start_founder_inbox_status():
    return _start_founder_inbox_watcher(force=False)


@app.post("/api/sloane/inbox/stop")
async def stop_founder_inbox_status():
    return _stop_founder_inbox_watcher()


@app.get("/api/hermes/runtime/status")
@app.get("/api/sloane/runtime/status")
async def get_sloane_runtime_status():
    return get_runtime_status()


@app.get("/api/telemetry/summary")
async def api_telemetry_summary(limit: int = 200):
    return get_telemetry_summary(limit=limit)


@app.get("/api/hermes/memory")
async def api_hermes_memory():
    return get_hermes_memory_snapshot()


@app.post("/api/hermes/mine-backlog")
async def api_hermes_mine_backlog(limit: int | None = None):
    return mine_historical_mel_backlog(limit=limit)

@app.post("/api/intervention/clear")
async def clear_intervention():
    """Founder clicks 'Resume Mission' — clears the alert."""
    global current_intervention
    if current_intervention:
        current_intervention["active"] = False
        audit_log({"event": "intervention_cleared", "service": current_intervention.get("service")})
    logging.info("✅ [INTERVENTION] Founder cleared the alert. Resuming operations.")
    return {"status": "cleared"}

@app.post("/api/hermes/jobs/test-session")
@app.post("/api/sloane/jobs/test-session")
async def create_sloane_test_session(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    mission_request = payload.get("request") or payload.get("message") or "Run a test operator mission."
    plan = plan_operator_mission(
        mission_request,
        {
            "requested_by": "Rob",
            "persona": "hermes",
            "target_agent": payload.get("target_agent") or payload.get("agent") or "dani",
            "intent_hint": "test_session_create",
            "source": "synapse_bridge_endpoint",
        },
    )
    result = execute_operator_plan(plan, {"args": payload, "start": True})
    job = result["job"]
    return {
        "status": "initiated",
        "job_id": job["job_id"],
        "phase": job["phase"],
        "recipient": job["spec"]["email_policy"]["recipient"],
        "job": normalize_job_to_mission(job),
    }

@app.get("/api/hermes/jobs")
@app.get("/api/sloane/jobs")
async def list_sloane_jobs():
    from tools.sloane_jobs import list_jobs
    return {"jobs": [normalize_job_to_mission(job) for job in list_jobs()]}

@app.get("/api/hermes/jobs/{job_id}")
@app.get("/api/sloane/jobs/{job_id}")
async def get_sloane_job(job_id: str):
    from tools.sloane_jobs import load_job
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Hermes job not found.")
    return normalize_job_to_mission(job)


@app.get("/api/hub/latest-results")
async def get_latest_results_summary():
    return {
        "mel": _build_latest_mel_summary(),
        "mission": _build_latest_job_summary(),
    }

@app.post("/api/hermes/jobs/{job_id}/approve-email")
@app.post("/api/sloane/jobs/{job_id}/approve-email")
async def approve_sloane_job_email(job_id: str):
    try:
        plan = plan_operator_mission(
            f"Approve outbound report email for {job_id}",
            {
                "requested_by": "Rob",
                "persona": "hermes",
                "intent_hint": "test_session_email",
                "source": "synapse_bridge_endpoint",
            },
        )
        job = execute_operator_plan(plan, {"args": {"job_id": job_id}})["job"]
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Hermes job not found.")
    return normalize_job_to_mission(job)

@app.post("/api/hermes/jobs/{job_id}/cancel")
@app.post("/api/sloane/jobs/{job_id}/cancel")
async def cancel_sloane_job(job_id: str):
    from tools.sloane_jobs import cancel_job
    try:
        job = cancel_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Hermes job not found.")
    return normalize_job_to_mission(job)

@app.post("/api/hermes/chat")
@app.post("/api/chat")
async def chat_with_sloane_route(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return await chat_with_hermes(payload)


async def chat_with_hermes(payload: dict):

    user_msg = str(payload.get("message") or "").strip()
    attachments = payload.get("attachments") or []
    attachment_context = _build_attachment_context_block(attachments)
    if not user_msg:
        raise HTTPException(status_code=400, detail="Empty message")
    is_forwarded_founder_email = user_msg.startswith("FOUNDER EMAIL RECEIVED.")
    
    global chat_history, last_inbox_lookup
    
    # Handle Reset Command
    if user_msg.lower() in ["!reset", "reset", "clear history"]:
        chat_history = []
        last_inbox_lookup = {}
        return {"reply": "Memory purged, Rob. Hermes is ready for a fresh start.", "agent": "Hermes"}

    effective_user_msg = user_msg if not attachment_context else f"{user_msg}\n\n{attachment_context}"
    chat_history.append({"role": "user", "content": effective_user_msg})
    if len(chat_history) > 10:
        chat_history = chat_history[-10:]

    site_report_key = None
    try:
        from tools.site_report_workflows import identify_site_report_request
        site_report_key = identify_site_report_request(user_msg)
    except Exception:
        site_report_key = "anam" if _is_anam_usage_email_request(user_msg) else None

    if site_report_key:
        from tools.site_report_workflows import SITE_REPORTS, run_site_usage_email_report
        recipient = _resolve_email_recipient(user_msg, FOUNDER_EMAIL)
        days = _extract_requested_days(user_msg, default=7)
        report = await run_site_usage_email_report(site_report_key, days=days, recipient=recipient)
        site_label = (SITE_REPORTS.get(site_report_key) or {}).get("label", site_report_key.title())
        if report.get("success"):
            sloane_reply = (
                f"Done. I checked {site_label}, captured the visible graphs, and sent the {days}-day report to {recipient}."
            )
        else:
            sloane_reply = (
                f"I checked {site_label} and assembled the report, but the email send failed for {recipient}."
            )
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes", "site_report": report}

    digest_send_match = re.search(
        r"(?:email|send).*?(?:list|digest).*?test sessions.*?(?:for|on|from)\s+([0-9]{1,2}[./][0-9]{1,2}[./][0-9]{2,4}|[A-Za-z]+\s+\d{1,2},\s*\d{4})",
        user_msg,
        re.IGNORECASE,
    )
    digest_reply_match = re.search(
        r"(?:list|show|summarize|summary).*?test sessions.*?(?:for|on|from)\s+([0-9]{1,2}[./][0-9]{1,2}[./][0-9]{2,4}|[A-Za-z]+\s+\d{1,2},\s*\d{4})",
        user_msg,
        re.IGNORECASE,
    )
    digest_resend_match = re.search(
        r"^(?:send|email)(?:\s+it)?\s+to\s+([\w\.-]+@[\w\.-]+\.\w+)\s*$",
        user_msg,
        re.IGNORECASE,
    )
    if digest_send_match:
        from tools.sloane_jobs import build_test_session_digest, parse_requested_date, _dispatch_email

        target_date = parse_requested_date(digest_send_match.group(1))
        recipient = _resolve_email_recipient(user_msg, FOUNDER_EMAIL)
        if not target_date:
            sloane_reply = "I can do that, but I need the date in a format I can parse cleanly."
            chat_history.append({"role": "assistant", "content": sloane_reply})
            return {"reply": sloane_reply, "agent": "Hermes"}
        digest = build_test_session_digest(target_date, recipient)
        dispatch = _dispatch_email(digest["subject"], digest["body"], recipient)
        if dispatch.get("success"):
            sloane_reply = (
                f"Done. I sent the {target_date.strftime('%B %d, %Y')} test-session digest to {recipient}."
            )
        else:
            sloane_reply = (
                f"I assembled the {target_date.strftime('%B %d, %Y')} test-session digest, but the email send failed."
            )
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes"}

    if digest_resend_match:
        from tools.sloane_jobs import build_test_session_digest, parse_requested_date, _dispatch_email

        raw_recent_date = _find_recent_requested_date(chat_history)
        target_date = parse_requested_date(raw_recent_date or "")
        recipient = digest_resend_match.group(1).strip().lower()
        if not target_date:
            sloane_reply = "I need the original digest date before I can resend that report cleanly."
            chat_history.append({"role": "assistant", "content": sloane_reply})
            return {"reply": sloane_reply, "agent": "Hermes"}
        digest = build_test_session_digest(target_date, recipient)
        dispatch = _dispatch_email(digest["subject"], digest["body"], recipient)
        if dispatch.get("success"):
            sloane_reply = (
                f"Done. I sent the {target_date.strftime('%B %d, %Y')} test-session digest to {recipient}."
            )
        else:
            sloane_reply = (
                f"I prepared the {target_date.strftime('%B %d, %Y')} test-session digest for {recipient}, but the send failed."
            )
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes"}

    if digest_reply_match and not digest_send_match:
        from tools.sloane_jobs import build_test_session_digest, parse_requested_date

        target_date = parse_requested_date(digest_reply_match.group(1))
        if not target_date:
            sloane_reply = "I can do that, but I need the date in a format I can parse cleanly."
            chat_history.append({"role": "assistant", "content": sloane_reply})
            return {"reply": sloane_reply, "agent": "Hermes"}
        digest = build_test_session_digest(target_date, "aifusionlabs@gmail.com")
        sloane_reply = digest["body"][:4000]
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes"}

    founder_reply_request = None if is_forwarded_founder_email else extract_founder_reply_request(user_msg)
    if founder_reply_request:
        dispatch = dispatch_founder_reply(
            founder_reply_request["body"],
            founder_reply_request["sender"],
        )
        if dispatch.get("success"):
            sloane_reply = "Done. I replied to your latest email."
        else:
            sloane_reply = "I prepared the founder reply, but the Gmail thread reply failed."
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes"}

    if _is_inbox_check_request(user_msg):
        execution = HERMES_EXECUTOR.execute(
            "GSUITE_INTENT",
            {
                "intent": "gmail_list",
                "target": "novaaifusionlabs@gmail.com",
                "limit": 5,
            },
            {
                "requested_by": "Rob",
                "persona": "hermes",
                "source": "synapse_bridge_fastpath",
                "chat_history": chat_history,
                "user_msg": user_msg,
            },
        )
        hermes_reply = execution.get("reply", "I checked the inbox.")
        chat_history.append({"role": "assistant", "content": hermes_reply})
        gmail_list = execution.get("gmail_list") or {}
        top_entry = (gmail_list.get("entries") or [None])[0] if isinstance(gmail_list, dict) else None
        last_inbox_lookup = {
            "account": "novaaifusionlabs@gmail.com",
            "sender": (top_entry or {}).get("sender", ""),
            "subject": (top_entry or {}).get("subject", ""),
            "summary": (top_entry or {}).get("summary", ""),
            "count": gmail_list.get("count", 0) if isinstance(gmail_list, dict) else 0,
        }
        response_payload = {"reply": hermes_reply, "agent": "Hermes"}
        if gmail_list:
            response_payload["gmail_list"] = gmail_list
        return response_payload

    if _is_inbox_detail_request(user_msg) and last_inbox_lookup:
        read_args = {
            "intent": "gmail_read_latest",
            "target": last_inbox_lookup.get("account") or "novaaifusionlabs@gmail.com",
        }
        if last_inbox_lookup.get("sender"):
            read_args["sender_filter"] = last_inbox_lookup["sender"]
        if last_inbox_lookup.get("subject"):
            read_args["query"] = last_inbox_lookup["subject"]

        execution = HERMES_EXECUTOR.execute(
            "GSUITE_INTENT",
            read_args,
            {
                "requested_by": "Rob",
                "persona": "hermes",
                "source": "synapse_bridge_fastpath",
                "chat_history": chat_history,
                "user_msg": user_msg,
            },
        )
        payload = execution.get("gmail_read_latest") or {}
        if payload.get("success"):
            body = str(payload.get("body") or "").strip()
            preview = body[:1600] if body else str(payload.get("body_preview") or "").strip()
            if preview:
                detail_reply = (
                    f"The latest email is from {payload.get('sender') or 'unknown sender'} with subject "
                    f"'{payload.get('subject') or 'No subject'}'.\n\n{preview}"
                )
            else:
                detail_reply = (
                    f"I located the email from {payload.get('sender') or 'unknown sender'} with subject "
                    f"'{payload.get('subject') or 'No subject'}', but Gmail did not expose the body text cleanly."
                )
        else:
            error_text = payload.get("error") or "Gmail did not return the email body."
            detail_reply = f"I found the message, but I could not read the full body cleanly: {error_text}"

        chat_history.append({"role": "assistant", "content": detail_reply})
        return {
            "reply": detail_reply,
            "agent": "Hermes",
            "gmail_read_latest": payload,
        }

    subscription_platform = _extract_subscription_platform(user_msg)
    if subscription_platform and re.search(r"\b(check|do we have|is there|look)\b", user_msg, re.IGNORECASE):
        card = find_subscription_card(subscription_platform)
        if card:
            details = []
            if card.get("cost"):
                details.append(f"amount {card['cost']}")
            if card.get("renewal_date"):
                details.append(f"bill date {card['renewal_date']}")
            detail_text = f" with {', '.join(details)}" if details else ""
            sloane_reply = f"Yes. The current subscription registry already has a {card.get('platform', subscription_platform)} card{detail_text}."
        else:
            sloane_reply = f"No. The current subscription registry does not show a {subscription_platform} card yet."
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes"}

    if re.search(r"\bwhat did you find out\b", user_msg, re.IGNORECASE):
        recent_platform = _find_recent_audit_target(chat_history[:-1])
        if recent_platform:
            card = find_subscription_card(recent_platform)
            if card:
                details = []
                if card.get("cost"):
                    details.append(f"amount {card['cost']}")
                if card.get("renewal_date"):
                    details.append(f"bill date {card['renewal_date']}")
                detail_text = f" It currently shows {', '.join(details)}." if details else ""
                sloane_reply = f"The current subscription registry does show a {card.get('platform', recent_platform)} card.{detail_text}"
            else:
                sloane_reply = f"The current subscription registry still does not show a {recent_platform} card."
            chat_history.append({"role": "assistant", "content": sloane_reply})
            return {"reply": sloane_reply, "agent": "Hermes"}

    if subscription_platform and re.search(r"\b(add|create|set up|setup)\b", user_msg, re.IGNORECASE) and "email" in user_msg.lower():
        email_payload = _read_latest_subscription_email(subscription_platform)
        if not email_payload.get("success"):
            sloane_reply = "I checked for the supporting email, but I could not read the latest matching thread cleanly. I have not changed the subscription registry yet."
            chat_history.append({"role": "assistant", "content": sloane_reply})
            return {"reply": sloane_reply, "agent": "Hermes", "email_lookup": email_payload}

        extracted = _extract_amount_and_bill_date(
            " ".join(
                [
                    str(email_payload.get("subject") or ""),
                    str(email_payload.get("body") or ""),
                    str(email_payload.get("body_preview") or ""),
                ]
            )
        )
        if not extracted.get("cost") and not extracted.get("renewal_date"):
            sloane_reply = (
                f"I found the latest matching {subscription_platform} email, but it did not expose a reliable amount or bill date for me to write into the registry. "
                "I have not changed the card yet."
            )
            chat_history.append({"role": "assistant", "content": sloane_reply})
            return {"reply": sloane_reply, "agent": "Hermes", "email_lookup": email_payload}

        card = upsert_subscription_card(
            subscription_platform,
            {
                "cost": extracted.get("cost", ""),
                "renewal_date": extracted.get("renewal_date", ""),
                "source_email_subject": email_payload.get("subject", ""),
                "source_email_sender": email_payload.get("sender", ""),
            },
            source="Hermes inbox-assisted update",
        )
        details = []
        if card.get("cost"):
            details.append(f"amount {card['cost']}")
        if card.get("renewal_date"):
            details.append(f"bill date {card['renewal_date']}")
        detail_text = ", ".join(details) if details else "partial details"
        sloane_reply = f"Done. I added the {card.get('platform', subscription_platform)} card to the subscription registry with {detail_text}."
        chat_history.append({"role": "assistant", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": "Hermes", "subscription_card": card}

    # Build Grounding Context
    now = datetime.now()
    current_time_str = now.strftime("%I:%M %p")
    current_date_str = now.strftime("%A, %B %d, %Y")
    report_files = glob.glob(os.path.join(REPORTS_DIR, 'USAGE_AUDIT_*.json'))
    last_sync = "Unknown"
    if report_files:
        latest = max(report_files, key=os.path.getctime)
        last_sync = os.path.basename(latest).replace('USAGE_AUDIT_', '').replace('.json', '')

    # Place grounding AFTER conversation so it stays in the model's attention window
    grounding_block = f"\n[CLOCK] Right now it is {current_time_str} on {current_date_str} (Phoenix/MST). Use THIS time if asked.\n[LAST AUDIT] {last_sync}\n"

    agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
    import yaml
    with open(agents_path, 'r', encoding='utf-8') as f:
        agents_data = yaml.safe_load(f)

    # 1. Parse @mention for direct board routing
    target_slug = payload.get("target_agent", "hermes")
    target_match = re.match(r'^@([\w-]+)\s*(.*)', user_msg, re.IGNORECASE)
    if target_match:
        potential_slug = target_match.group(1).lower()
        # Verify slug exists
        if any(a["slug"] == potential_slug for a in agents_data.get("agents", [])):
            target_slug = potential_slug
            user_msg = target_match.group(2).strip() or "Hello."

    # 2. Determine Target Persona
    target_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == target_slug), None)
    base_persona = target_conf.get("persona", MONEYPENNY_PROMPT) if target_conf else MONEYPENNY_PROMPT
    target_name = target_conf.get("name", "Hermes") if target_conf else "Hermes"

    try:
        runtime_res = generate_sloane_response(
            base_persona=base_persona,
            chat_history=chat_history,
            grounding_block=grounding_block,
            target_name=target_name,
        )
        sloane_reply = runtime_res.get("text", "").strip()
        
        # Log Interaction
        audit_log({"event": "chat", "user": user_msg, "response": sloane_reply, "runtime": runtime_res})
        
        # --- PARSE X_LINK_CALL ---
        if "X_LINK_CALL" in sloane_reply:
            try:
                tool_call = _extract_single_tool_call(sloane_reply)
                if tool_call:
                    call_data = tool_call["payload"]
                    if tool_call.get("suffix"):
                        logging.warning("Ignoring trailing text after X_LINK_CALL: %s", tool_call["suffix"][:240])
                    action = call_data.get("action")
                    args = call_data.get("args", {})
                    executor_context = {
                        "requested_by": "Rob",
                        "persona": "hermes",
                        "source": "synapse_bridge_chat",
                        "chat_history": chat_history,
                        "user_msg": user_msg,
                    }

                    safe_executor_actions = {
                        "TEST_SESSION_CREATE",
                        "TEST_SESSION_STATUS",
                        "TEST_SESSION_REPORT",
                        "TEST_SESSION_EMAIL",
                        "TEST_SESSION_DIGEST_EMAIL",
                        "FOUNDER_EMAIL_REPLY",
                        "GSUITE_INTENT",
                        "BROWSER_SCOUT",
                        "EXEC_AUDIT",
                        "SYNC_ENGINES",
                        "GEN_BRIEFING",
                        "EXEC_ARCHIVE",
                    }
                    if action in safe_executor_actions:
                        execution = HERMES_EXECUTOR.execute(action, args, executor_context)
                        sloane_reply = execution.get("reply", "Hermes completed the requested action.")
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        response_payload = {"reply": sloane_reply, "agent": "Hermes"}
                        if execution.get("job_id"):
                            response_payload["job_id"] = execution["job_id"]
                        if execution.get("pid"):
                            response_payload["pid"] = execution["pid"]
                        if execution.get("gmail_list") is not None:
                            response_payload["gmail_list"] = execution["gmail_list"]
                        return response_payload

                    # --- SLOANE TEST OPERATOR ---
                    if action == "TEST_SESSION_CREATE":
                        mission_request = user_msg
                        job_args = dict(args or {})
                        if "request" not in job_args:
                            job_args["request"] = mission_request
                        plan = plan_operator_mission(
                            mission_request,
                            {
                                "requested_by": "Rob",
                                "persona": "hermes",
                                "target_agent": job_args.get("target_agent") or job_args.get("agent") or "dani",
                                "intent_hint": "test_session_create",
                                "source": "synapse_bridge_chat",
                                "chat_history": chat_history,
                            },
                        )
                        result = execute_operator_plan(plan, {"args": job_args, "start": True})
                        job = result["job"]
                        sloane_reply = render_operator_reply(result, persona="hermes")
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes", "job_id": job["job_id"]}

                    if action == "TEST_SESSION_STATUS":
                        plan = plan_operator_mission(
                            user_msg,
                            {
                                "requested_by": "Rob",
                                "persona": "hermes",
                                "intent_hint": "test_session_status",
                                "source": "synapse_bridge_chat",
                                "chat_history": chat_history,
                            },
                        )
                        result = execute_operator_plan(plan, {"args": dict(args or {})})
                        sloane_reply = render_operator_reply(result, persona="hermes")
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes"}

                    if action == "TEST_SESSION_REPORT":
                        plan = plan_operator_mission(
                            user_msg,
                            {
                                "requested_by": "Rob",
                                "persona": "hermes",
                                "intent_hint": "test_session_report",
                                "source": "synapse_bridge_chat",
                                "chat_history": chat_history,
                            },
                        )
                        result = execute_operator_plan(plan, {"args": dict(args or {})})
                        job = result.get("job")
                        report_path = job.get("artifacts", {}).get("report_text") if job else None
                        if report_path and os.path.exists(report_path):
                            with open(report_path, "r", encoding="utf-8") as rf:
                                sloane_reply = rf.read()[:4000]
                        else:
                            sloane_reply = render_operator_reply(result, persona="hermes")
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes"}

                    if action == "TEST_SESSION_EMAIL":
                        plan = plan_operator_mission(
                            user_msg,
                            {
                                "requested_by": "Rob",
                                "persona": "hermes",
                                "intent_hint": "test_session_email",
                                "source": "synapse_bridge_chat",
                                "chat_history": chat_history,
                            },
                        )
                        result = execute_operator_plan(plan, {"args": dict(args or {})})
                        sloane_reply = render_operator_reply(result, persona="hermes")
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes"}

                    if action == "TEST_SESSION_DIGEST_EMAIL":
                        from tools.sloane_jobs import build_test_session_digest, parse_requested_date, _dispatch_email

                        target_date = parse_requested_date(args.get("target_date", ""))
                        recipient = (args.get("recipient") or "aifusionlabs@gmail.com").strip().lower()
                        if not target_date:
                            sloane_reply = "I need a valid date before I can send that test-session digest."
                        else:
                            digest = build_test_session_digest(target_date, recipient)
                            dispatch = _dispatch_email(digest["subject"], digest["body"], recipient)
                            if dispatch.get("success"):
                                sloane_reply = f"Understood. I sent the {target_date.strftime('%B %d, %Y')} test-session digest to {recipient}."
                            else:
                                sloane_reply = f"I prepared the {target_date.strftime('%B %d, %Y')} test-session digest, but the send failed."
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes"}

                    if action == "FOUNDER_EMAIL_REPLY":
                        body = (args.get("body") or "").strip()
                        if not body:
                            sloane_reply = "I need the reply text before I can answer your latest email."
                        else:
                            dispatch = dispatch_founder_reply(body)
                            if dispatch.get("success"):
                                sloane_reply = "Done. I replied to your latest email."
                            else:
                                sloane_reply = "I prepared the founder reply, but the Gmail thread reply failed."
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes"}

                    # --- BOARD ROOM DELEGATION (INTERNAL) ---
                    if action == "AGENT_BRIEFING":
                        target = args.get("target")
                        task_msg = args.get("message")
                        
                        # Load agent persona
                        agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
                        import yaml
                        with open(agents_path, 'r', encoding='utf-8') as f:
                            agents_data = yaml.safe_load(f)
                        
                        agent_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == target), None)
                        if not agent_conf:
                            sloane_reply = f"I'm sorry Rob, but '{target}' does not exist in our internal personnel records."
                        else:
                            # Call internal agent
                            system_persona = agent_conf.get("persona", "You are an internal Board Room specialist.")
                            agent_prompt = f"SYSTEM: {system_persona}\n\nUSER (Sloane): {task_msg}\n\nREPLY:"
                            
                            agent_resp = requests.post("http://127.0.0.1:11434/api/generate", json={
                                "model": "qwen2.5:14b-instruct-q6_K",
                                "prompt": agent_prompt,
                                "stream": False,
                                "options": {"temperature": 0.4}
                            }, timeout=120)
                            agent_resp.raise_for_status()
                            agent_output = agent_resp.json().get("response", "").strip()
                            
                            # Log to audit
                            audit_log({"event": "board_briefing", "target": target, "task": task_msg, "response": agent_output})
                            
                            sloane_reply = f"Mission dispatched to {agent_conf.get('name')}. They have responded with the following:\n\n\"{agent_output}\""
                            
                        # Update history with the final "reported" version
                        chat_history.append({"role": "assistant", "content": sloane_reply})
                        return {"reply": sloane_reply, "agent": "Hermes"}
                    
                    if not action:
                        raise ValueError("Missing 'action' key in JSON")

                    # Map actions to tools (v3 keys)
                    action_to_tool = {
                        "EXEC_AUDIT": "usage_auditor",
                        "SYNC_ENGINES": "usage_auditor",
                        "BROWSER_SCOUT": "browser_scout",
                        "GEN_BRIEFING": "briefing",
                        "GSUITE_INTENT": "gsuite",
                        "DISCORD_INTENT": "discord",
                        "EXEC_ARCHIVE": "great_archivist"
                    }

                    
                    if action in action_to_tool:
                        tool_key = action_to_tool[action]
                        
                        if tool_key == "gsuite":
                            intent = args.get("intent")
                            if not intent:
                                raise ValueError("GSUITE_INTENT missing 'intent' key (gmail_send, gmail_list, or calendar_create)")
                            
                            g_args = [PYTHON_EXE, os.path.join(ROOT_DIR, "tools", "gsuite_handler.py"), "--action", intent]
                            if intent == "gmail_send":
                                to_addr = args.get("target")
                                if not to_addr:
                                    raise ValueError("gmail_send requires 'target' (recipient email address)")
                                subject = args.get("subject", "Message from Sloane")
                                body = args.get("body", args.get("constraints", ""))
                                g_args += ["--to", to_addr, "--subject", subject, "--body", body]
                            elif intent == "gmail_list":
                                account = args.get("target") or "novaaifusionlabs@gmail.com"
                                limit = str(args.get("limit") or 5)
                                sender_filter = str(args.get("sender_filter") or args.get("sender") or "")
                                g_args += ["--account", account, "--limit", limit]
                                if sender_filter:
                                    g_args += ["--sender-filter", sender_filter]
                                proc = subprocess.run(g_args, capture_output=True, text=True, cwd=ROOT_DIR)
                                try:
                                    payload = json.loads((proc.stdout or "").strip() or "{}")
                                except json.JSONDecodeError:
                                    payload = {"success": False, "error": (proc.stdout or proc.stderr or "").strip(), "entries": []}
                                if not payload.get("success"):
                                    error_text = payload.get("error") or (proc.stderr or "Inbox inspection failed.")
                                    sloane_reply = f"I tried to check the inbox, but the read failed: {error_text}"
                                else:
                                    entries = payload.get("entries") or []
                                    if not entries:
                                        sloane_reply = "I checked the inbox. Nothing new is waiting at the moment."
                                    else:
                                        top = entries[0]
                                        sender = top.get("sender") or "unknown sender"
                                        subject = top.get("subject") or "No subject"
                                        count = payload.get("count", len(entries))
                                        sloane_reply = (
                                            f"Yes. I checked the inbox. The latest message is from {sender} with subject '{subject}'. "
                                            f"I can see {count} recent message{'s' if count != 1 else ''}."
                                        )
                                chat_history.append({"role": "assistant", "content": sloane_reply})
                                return {"reply": sloane_reply, "agent": "Hermes", "gmail_list": payload}
                            elif intent == "calendar_create":
                                title = args.get("target", "Sloane Meeting")
                                description = args.get("description", args.get("constraints", ""))
                                g_args += ["--title", title, "--description", description]
                            else:
                                raise ValueError(f"Unknown GSUITE_INTENT intent: {intent}. Use gmail_send, gmail_list, or calendar_create.")
                            subprocess.Popen(g_args)
                            sloane_reply = f"Acknowledged. GSuite mission dispatched for {intent}. 📅📧"
                        
                        elif tool_key == "browser_scout":
                            url = args.get("url")
                            subprocess.Popen([PYTHON_EXE, os.path.join(ROOT_DIR, "tools", "browser_scout.py"), "--url", url])
                            sloane_reply = f"Acknowledged. Scouting the target URL: {url}. I'll inform you when the intelligence is archived. 🕵️‍♀️🛰️"

                        elif tool_key == "discord":
                             subprocess.Popen([PYTHON_EXE, os.path.join(ROOT_DIR, "tools", "discord_watcher.py")])
                             sloane_reply = "Acknowledged. Discord mission dispatched. 👠🎧"
                        
                        else:
                            await trigger_tool(tool_key)
                            sloane_reply = f"Acknowledged. Initiating {action} mission background... 🛰️🚀"
            except Exception as parse_err:
                logging.error(f"Failed to parse X_LINK_CALL: {parse_err}")
                sloane_reply += f"\n\n[SYSTEM ERROR: Malformed Tool Call - {str(parse_err)}]"

        chat_history.append({"role": "sloane", "content": sloane_reply})
        return {"reply": sloane_reply, "agent": target_name}
    except Exception as e:
        logging.error(f"Chat error: {e}")
        return {"reply": "Communication relay failure. Verify Ollama is running.", "agent": "Hermes"}


async def chat_with_sloane(payload: dict):
    """Compatibility shim while legacy callers finish migrating to the Hermes-first surface."""
    return await chat_with_hermes(payload)

# ── MEL (Superhero Agent) API Routes ──────────────────────────

@app.get("/api/mel/list_agents")
async def mel_list_agents():
    """List all available agents for evolution."""
    try:
        from tools.mel_pilot import get_available_agents
        agents = get_available_agents()
        return {"status": "ok", "agents": agents, "count": len(agents)}
    except Exception as e:
        logging.error(f"MEL agent listing failed: {e}")
        return {"status": "error", "error": str(e), "agents": [], "count": 0}


@app.post("/api/mel/evolve")
async def mel_evolve(request: Request):
    """Trigger a MEL evolution loop for an agent. Text-to-text only."""
    try:
        body = await request.json()
    except:
        body = {}
    agent = body.get("agent", "")
    scenarios = body.get("scenarios", 3)
    max_turns = body.get("max_turns", 8)
    pack = body.get("scenario_pack") or body.get("pack") or "default_pack"
    difficulty = body.get("difficulty", "mixed")
    engine_version = body.get("engine") or body.get("version") or "v1"

    if not agent:
        raise HTTPException(status_code=400, detail="'agent' is required.")

    # 1. Resolve Pack: If defaulting or missing, check agents.yaml
    if pack == "default_pack":
        try:
            from tools.mel_pilot import load_agent_config, resolve_mel_scenario_pack
            conf = load_agent_config(agent)
            resolved_pack = resolve_mel_scenario_pack(
                agent_slug=agent,
                requested_pack=pack,
                difficulty=difficulty,
                agent_config=conf,
            )
            if resolved_pack != pack:
                pack = resolved_pack
                logging.info(f"📍 Auto-resolved MEL pack for '{agent}' -> '{pack}'")
        except Exception as exc:
            logging.warning(f"Unable to auto-resolve MEL pack for '{agent}': {exc}")

    logging.info(f"🦸 MEL Evolution triggered for '{agent}' (scenarios={scenarios}, turns={max_turns}, pack={pack}, diff={difficulty})")

    from tools.mel_pilot import PID_FILE
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as fh:
                current_pid = fh.read().strip()
        except Exception:
            current_pid = ""
        if current_pid and _pid_is_alive(current_pid):
            return {
                "status": "already_running",
                "agent": agent,
                "pid": int(current_pid),
                "detail": "A MEL evolution cycle is already running. Stop it first or wait for it to finish.",
            }
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    # Launch as subprocess to avoid blocking the Hub
    mel_entry = "mel_v2_runner.py" if str(engine_version).lower() == "v2" else "mel_pilot.py"
    mel_args = [
        PYTHON_EXE, os.path.join(ROOT_DIR, "tools", mel_entry),
        "--agent", agent,
        "--pack", pack,
        "--scenarios", str(scenarios),
        "--turns", str(max_turns),
    ]
    if difficulty != "mixed":
        # Check if mel_pilot supports difficulty flag
        mel_args.extend(["--difficulty", difficulty])
    try:
        _write_mel_progress_bootstrap(
            agent=agent,
            detail=f"Launching evolution engine for {agent} ({scenarios} scenarios, {max_turns if max_turns else 'limitless'} turns)...",
            running=True,
            status="active",
            pct=1,
            data={
                "scenario_pack": pack,
                "difficulty": difficulty,
                "scenarios": scenarios,
                "max_turns": max_turns,
            },
        )
        proc = subprocess.Popen(mel_args, cwd=ROOT_DIR)
        active_procs["mel_evolve"] = {"pid": proc.pid, "started_at": datetime.now().isoformat(), "agent": agent}
        return {
            "status": "initiated",
            "agent": agent,
            "scenario_pack": pack,
            "difficulty": difficulty,
            "pid": proc.pid,
            "scenarios": scenarios,
            "max_turns": max_turns,
            "engine": engine_version,
        }
    except Exception as e:
        logging.error(f"❌ MEL launch failed: {e}")
        _write_mel_progress_bootstrap(
            agent=agent,
            detail=f"Failed to launch MEL: {e}",
            running=False,
            status="error",
            pct=0,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mel/stop")
async def mel_stop():
    """Abort an active MEL evolution session."""
    global active_procs
    
    PID_FILE = os.path.join(ROOT_DIR, "vault", "mel", "session.pid")
    pid_killed = False

    try:
        # 1. Deterministic Kill via PID file
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r") as f:
                    pid = f.read().strip()
                if pid:
                    subprocess.call(["taskkill", "/F", "/T", "/PID", pid], shell=True)
                    logging.info(f"🛑 [MEL] Killed pilot via PID file: {pid}")
                    pid_killed = True
                os.remove(PID_FILE)
            except Exception as e:
                logging.error(f"Failed to kill via PID file: {e}")

        # 2. Fallback: Robust kill using WMI through PowerShell (for stray orphans)
        if not pid_killed:
            ps_cmd = 'powershell -Command "Get-WmiObject Win32_Process -Filter \\"name=\'python.exe\' AND CommandLine LIKE \'%mel_pilot.py%\'\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"'
            try:
                subprocess.call(ps_cmd, shell=True)
                logging.info("🛑 [MEL] Killed pilot processes via WMI/PowerShell fallback.")
            except:
                pass # No processes found or PS error

        if "mel_evolve" in active_procs:
            del active_procs["mel_evolve"]
            
        # Update progress file to reflect stopped state
        try:
            PROGRESS_FILE = os.path.join(ROOT_DIR, "vault", "mel", "progress.json")
            if os.path.exists(PROGRESS_FILE):
                with open(PROGRESS_FILE, "r") as f:
                    data = json.load(f)
                data["running"] = False
                with open(PROGRESS_FILE, "w") as f:
                    json.dump(data, f)
        except Exception as e:
            logging.error(f"Failed to update progress file during stop: {e}")

        return {"status": "stopped"}
    except Exception as e:
        logging.error(f"❌ Failed to stop MEL process: {e}")
        return {"status": "error", "message": str(e)}



@app.get("/api/mel/progress")
async def mel_progress():
    """Return live MEL progress data for the animated timeline with liveness check."""
    try:
        from tools.mel_pilot import load_progress, summarize_progress, PID_FILE, PROGRESS_FILE
        data = load_progress()
        
        # Liveness Pulse: If marked as running, verify process actually exists in OS
        if data.get("running"):
            is_stale = True
            if os.path.exists(PID_FILE):
                try:
                    with open(PID_FILE, "r") as f:
                        pid = f.read().strip()
                    if pid:
                        # Check if process exists on Windows
                        check = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], encoding='utf-8')
                        if "python.exe" in check.lower():
                            is_stale = False
                except:
                    pass
            
            if is_stale:
                logging.warning(f"⚠️ [Liveness Pulse] Detected silent crash of MEL session. Auto-clearing state.")
                data["running"] = False
                try:
                    # Update progress file on disk to prevent future ghosts
                    if os.path.exists(PROGRESS_FILE):
                        with open(PROGRESS_FILE, "r") as f:
                            disk_data = json.load(f)
                        disk_data["running"] = False
                        with open(PROGRESS_FILE, "w") as f:
                            json.dump(disk_data, f)
                    if os.path.exists(PID_FILE):
                        os.remove(PID_FILE)
                except Exception as e:
                    logging.error(f"Failed to auto-clear ghost session: {e}")

        return summarize_progress(data)
    except Exception as e:
        logging.error(f"MEL progress fetch error: {e}")
        return {"running": False, "agent": "", "events": []}


@app.get("/api/mel/pending")
async def mel_pending():
    """Return all pending MEL approval items."""
    try:
        from tools.mel_pilot import load_pending_approvals
        approvals = load_pending_approvals()
        return {"status": "ok", "pending": approvals, "count": len(approvals)}
    except Exception as e:
        logging.error(f"MEL pending fetch error: {e}")
        return {"status": "error", "error": str(e), "pending": [], "count": 0}


@app.post("/api/mel/approve")
async def mel_approve(request: Request):
    """Approve a pending MEL prompt patch — applies it to agents.yaml."""
    try:
        body = await request.json()
    except:
        body = {}
    pending_id = body.get("pending_id", "")
    if not pending_id:
        raise HTTPException(status_code=400, detail="'pending_id' is required.")

    try:
        from tools.mel_pilot import apply_approval
        result = apply_approval(pending_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"MEL approve error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mel/reject")
async def mel_reject(request: Request):
    """Reject a pending MEL prompt patch."""
    try:
        body = await request.json()
    except:
        body = {}
    pending_id = body.get("pending_id", "")
    if not pending_id:
        raise HTTPException(status_code=400, detail="'pending_id' is required.")

    try:
        from tools.mel_pilot import reject_approval
        result = reject_approval(pending_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"MEL reject error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mel/checkpoint")
async def mel_checkpoint(request: Request):
    try:
        body = await request.json()
    except:
        body = {}
    agent_slug = body.get("agent_slug", "")
    if not agent_slug:
        raise HTTPException(status_code=400, detail="'agent_slug' is required.")
    label = body.get("label", "manual")
    notes = body.get("notes", "")

    try:
        from tools.mel_pilot import create_persona_checkpoint
        result = create_persona_checkpoint(agent_slug, label=label, notes=notes, source="hub")
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"MEL checkpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mel/checkpoints")
async def mel_checkpoints(agent_slug: str = "", limit: int = 20):
    try:
        from tools.mel_pilot import list_persona_checkpoints
        rows = list_persona_checkpoints(agent_slug=agent_slug, limit=limit)
        return {"status": "ok", "checkpoints": rows, "count": len(rows)}
    except Exception as e:
        logging.error(f"MEL checkpoints fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mel/rollback")
async def mel_rollback(request: Request):
    try:
        body = await request.json()
    except:
        body = {}
    checkpoint_id = body.get("checkpoint_id", "")
    if not checkpoint_id:
        raise HTTPException(status_code=400, detail="'checkpoint_id' is required.")

    try:
        from tools.mel_pilot import restore_persona_checkpoint
        result = restore_persona_checkpoint(checkpoint_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"MEL rollback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/hub")
async def get_hub_redirect():
    return RedirectResponse(url="/hub/")

# Serve the Hub UI and its assets from /hub
app.mount("/hub", NoCacheStaticFiles(directory=HUB_DIR, html=True), name="hub")
# Legacy /assets mount for older references to style.css/app.js
app.mount("/assets", NoCacheStaticFiles(directory=HUB_DIR), name="assets")
app.mount("/vault", NoCacheStaticFiles(directory=VAULT_DIR), name="vault")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5001)

