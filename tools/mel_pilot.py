"""
X-LINK Micro-Experimentation Loop (MEL) — Superhero Agent Engine
Generates prompt patch candidates via Troy, tests them against
the Dojo sim (text-to-text only, zero Anam tokens), and stages
results for human approval.

Usage:
    python tools/mel_pilot.py --agent amy --scenarios 3
"""

import os
import sys
import json
import uuid
import yaml
import asyncio
import logging
import requests
import glob
import signal
import atexit
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

PID_FILE = os.path.join(ROOT_DIR, "vault", "mel", "session.pid")
PROGRESS_FILE = os.path.join(ROOT_DIR, "vault", "mel", "progress.json")

def update_progress_not_running():
    """Ensure the Hub knows this process is no longer active."""
    try:
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r") as f:
                data = json.load(f)
            data["running"] = False
            with open(PROGRESS_FILE, "w") as f:
                json.dump(data, f)
    except: pass

def register_session():
    """Register the current PID for the Hub to kill if needed."""
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(cleanup_session)
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

def cleanup_session():
    """Cleanup PID registration and mark status as not running on exit."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except: pass
    update_progress_not_running()

from tools.xagent_eval.schemas import EvalInputs, BatchSummary
from tools.xagent_eval.batch_runner import execute_simulated_run, aggregate_batch, save_run_artifacts, save_batch_artifacts
from tools.xagent_eval.scenario_bank import select_scenarios
from tools.xagent_eval.reviewer_runner import ReviewerRunner
from tools.hermes_mel import build_batch_plan, persist_batch_manifest
from tools.hermes_memory import load_lessons, record_lesson
from tools.telemetry import capture_gpu_sample, record_workflow_run

logger = logging.getLogger("mel_pilot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [MEL] %(message)s")

VAULT_DIR = os.path.join(ROOT_DIR, "vault")
MEL_DIR = os.path.join(VAULT_DIR, "mel")
HISTORY_DIR = os.path.join(MEL_DIR, "history")
PENDING_DIR = os.path.join(MEL_DIR, "pending")
CHECKPOINTS_DIR = os.path.join(MEL_DIR, "checkpoints")
AGENTS_YAML = os.path.join(ROOT_DIR, "config", "agents.yaml")
TROY_CONFIG = os.path.join(ROOT_DIR, "config", "review_team", "troy.yaml")
OLLAMA_URL = "http://127.0.0.1:11434"
PROGRESS_FILE = os.path.join(MEL_DIR, "progress.json")
LOG_DIR = os.path.join(MEL_DIR, "logs")

# ── Forensic Logging ───────────────────────────────────────────

class SessionLogger:
    def __init__(self, session_id: str):
        self.session_id = session_id
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(LOG_DIR, f"session_{session_id}.log")
        
    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception as e:
            logger.error(f"Failed to write to session log: {e}")

session_logger: Optional[SessionLogger] = None


# ── Progress Broadcasting ─────────────────────────────────────

def emit_progress(stage: str, status: str, detail: str = "", pct: int = 0, agent: str = "", data: dict = None):
    """Write a progress event to vault/mel/progress.json for the Hub to poll."""
    os.makedirs(MEL_DIR, exist_ok=True)
    event = {
        "stage": stage,
        "status": status,       # active | done | error
        "detail": detail,
        "pct": pct,             # 0-100 overall progress
        "agent": agent,
        "timestamp": datetime.now().isoformat(),
        "data": data or {},
    }

    # Load existing events or start fresh
    events = []
    last_pct = 0
    if os.path.isfile(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress = json.load(f)
            events = progress.get("events", [])
            last_pct = progress.get("last_pct", 0)
        except Exception:
            events = []

    # Prevent percentage jitter (don't go backwards)
    stable_pct = max(pct, last_pct)

    # Limit list to last 50 events to prevent Hub UI bloat
    events.append(event)
    if len(events) > 50:
        events = events[-50:]

    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        # running is True unless we hit a terminal stage
        is_running = stage not in ["complete", "error"]
        json.dump({
            "running": is_running, 
            "agent": agent, 
            "last_pct": stable_pct, 
            "events": events
        }, f, indent=2)

    msg = f"[{stable_pct}%] {stage}: {detail}"
    logger.info(f"[PROGRESS] {msg}")
    if session_logger:
        session_logger.log(msg)


def load_progress() -> dict:
    """Load current progress data."""
    if not os.path.isfile(PROGRESS_FILE):
        return {"running": False, "agent": "", "events": []}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"running": False, "agent": "", "events": []}


def summarize_progress(progress: dict) -> dict:
    """Add a Hub-friendly summary layer to raw MEL progress data."""
    events = progress.get("events", []) or []
    last_event = events[-1] if events else {}
    first_event = events[0] if events else {}
    now = datetime.now()

    current_stage = last_event.get("stage") or ("idle" if not progress.get("running") else "queued")
    current_detail = last_event.get("detail") or ("Evolution cycle running." if progress.get("running") else "No active evolution cycle.")
    current_status = last_event.get("status") or ("active" if progress.get("running") else "idle")
    last_pct = progress.get("last_pct", 0)

    last_event_age_seconds = None
    timestamp = last_event.get("timestamp")
    if timestamp:
        try:
            last_event_age_seconds = max(0, int((now - datetime.fromisoformat(timestamp)).total_seconds()))
        except ValueError:
            last_event_age_seconds = None

    warnings: List[str] = []
    for event in reversed(events):
        if event.get("status") == "error":
            detail = str(event.get("detail") or "").strip()
            if detail and detail not in warnings:
                warnings.append(detail)
        if len(warnings) >= 3:
            break

    scoring_stages = {"baseline", "challenger_1", "challenger_2"}
    if (
        progress.get("running")
        and current_stage in scoring_stages
        and last_event_age_seconds is not None
        and last_event_age_seconds >= 45
    ):
        warnings.insert(0, f"No new MEL event for {last_event_age_seconds}s. SH Lab is likely still scoring.")

    summary_state = "idle"
    if current_status == "error":
        summary_state = "error"
    elif warnings:
        summary_state = "warning"
    elif progress.get("running"):
        summary_state = "running"
    elif current_stage == "complete":
        summary_state = "completed"

    summary = {
        "state": summary_state,
        "current_stage": current_stage,
        "current_status": current_status,
        "stage_label": current_stage.replace("_", " ").title(),
        "current_detail": current_detail,
        "last_pct": last_pct,
        "last_event_age_seconds": last_event_age_seconds,
        "last_event_timestamp": last_event.get("timestamp"),
        "started_at": first_event.get("timestamp"),
        "warnings": warnings[:3],
        "latest_error": warnings[0] if warnings else None,
    }

    enriched = dict(progress)
    enriched["summary"] = summary
    return enriched


def reset_progress():
    """Clear progress file for a fresh run."""
    os.makedirs(MEL_DIR, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"running": False, "agent": "", "events": []}, f)


# ── Pre-Flight ────────────────────────────────────────────────

def preflight_check() -> bool:
    """Ping Ollama to ensure it's running."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            logger.info("✅ Ollama is online.")
            return True
    except Exception:
        pass
    logger.error("❌ Ollama is NOT reachable. Start Ollama before running MEL.")
    return False


# ── Agent Loading ─────────────────────────────────────────────

def load_agent_config(agent_slug: str) -> Dict[str, Any]:
    """Load a single agent's config from agents.yaml."""
    with open(AGENTS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for agent in data.get("agents", []):
        if agent.get("slug") == agent_slug:
            return agent
    raise ValueError(f"Agent '{agent_slug}' not found in agents.yaml")


def resolve_agent_eval_defaults(agent_config: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Resolve agent-specific default scenario pack and rubric from agents.yaml."""
    eval_block = agent_config.get("eval", {}) or {}
    return eval_block.get("default_pack"), eval_block.get("scoring_rubric")


def resolve_mel_scenario_pack(
    agent_slug: str,
    requested_pack: str = "default_pack",
    difficulty: str = "mixed",
    agent_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Resolve the scenario pack MEL should actually use for this run."""
    if requested_pack and requested_pack != "default_pack":
        return requested_pack

    config = agent_config or load_agent_config(agent_slug)
    eval_block = config.get("eval", {}) or {}
    allowed_packs = list(eval_block.get("allowed_packs") or [])
    eval_default_pack = eval_block.get("default_pack")
    packs_dir = os.path.join(ROOT_DIR, "config", "eval_scenarios")
    normalized_difficulty = str(difficulty or "mixed").strip().lower()

    def _usable(pack_name: Optional[str]) -> bool:
        if not pack_name:
            return False
        if allowed_packs and pack_name not in allowed_packs:
            return False
        return os.path.exists(os.path.join(packs_dir, f"{pack_name}.yaml"))

    if normalized_difficulty in {"cooperative", "mixed", "hard", "extreme"}:
        for candidate in (
            f"{agent_slug}_frontdoor_discovery",
            f"{agent_slug}_it_discovery",
            f"{agent_slug}_platform_sales",
            f"{agent_slug}_field_service",
            f"{agent_slug}_pack",
        ):
            if _usable(candidate):
                return candidate

    if _usable(eval_default_pack):
        return eval_default_pack

    for candidate in (f"{agent_slug}_platform_sales", f"{agent_slug}_pack"):
        if _usable(candidate):
            return candidate

    return requested_pack or "default_pack"


def get_available_agents() -> List[Dict[str, Any]]:
    """Return a list of all agents in agents.yaml."""
    try:
        with open(AGENTS_YAML, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("agents", [])
    except Exception as e:
        logger.error(f"Failed to load available agents: {e}")
        return []


# ── Diagnostic Extraction (Sloane's Role) ─────────────────────

def extract_diagnostic(agent_slug: str, batch_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extract the weakest scoring category as the diagnostic.
    If batch_data is provided, use it directly. Otherwise, find the most recent.
    """
    if batch_data:
        best_batch = batch_data
    else:
        batches_dir = os.path.join(VAULT_DIR, "evals", "batches")
        if not os.path.isdir(batches_dir):
            logger.warning("No evals/batches directory found. Using default diagnostic.")
            return _default_diagnostic(agent_slug)

        # Find most recent batch for this agent
        best_batch = None
        best_time = ""
        for batch_id in os.listdir(batches_dir):
            summary_path = os.path.join(batches_dir, batch_id, "batch_summary.json")
            if not os.path.isfile(summary_path):
                continue
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary = json.load(f)
                if summary.get("target_agent") == agent_slug:
                    ts = summary.get("batch_id", "")
                    if ts > best_time:
                        best_time = ts
                        best_batch = summary
            except Exception:
                continue

    if not best_batch:
        logger.info(f"No previous batch data for '{agent_slug}'. Using default diagnostic.")
        return _default_diagnostic(agent_slug)

    # Extract weakest category
    cat_avgs = best_batch.get("category_averages", {})
    top_failures = best_batch.get("top_failure_categories", [])
    
    weakest_cat = top_failures[0] if top_failures else (
        min(cat_avgs, key=cat_avgs.get) if cat_avgs else "general_performance"
    )
    weakest_score = cat_avgs.get(weakest_cat, 0)
    if weakest_score <= 5:
        failure_rate = round(((5.0 - weakest_score) / 5.0) * 100, 1)
    else:
        failure_rate = round(100 - weakest_score, 1)

    # Try to find a failed exchange snippet
    failed_snippet = _find_failed_snippet(agent_slug, best_batch)

    baseline_score = best_batch.get("average_score")
    if baseline_score is None:
        baseline_score = best_batch.get("score", 0)

    baseline_pass_rate = best_batch.get("pass_rate")
    if baseline_pass_rate is None:
        baseline_pass_rate = best_batch.get("baseline_pass_rate", 0)

    return {
        "failure_category": weakest_cat,
        "failure_rate": failure_rate,
        "baseline_score": baseline_score,
        "baseline_pass_rate": baseline_pass_rate,
        "failed_exchange": failed_snippet,
        "batch_id": best_batch.get("batch_id", "unknown"),
    }


def _default_diagnostic(agent_slug: str) -> Dict[str, Any]:
    """Fallback diagnostic when no batch data exists."""
    return {
        "failure_category": "general_performance",
        "failure_rate": 0,
        "baseline_score": 0,
        "baseline_pass_rate": 0,
        "failed_exchange": "No previous eval data available.",
        "batch_id": "none",
    }


def _find_failed_snippet(agent_slug: str, batch: dict) -> str:
    """Find a transcript snippet from a failed run."""
    runs_dir = os.path.join(VAULT_DIR, "evals", "runs")
    runs_payload = batch.get("runs", []) or []

    for run in runs_payload:
        if run.get("pass_fail") not in ("FAIL", "FAIL_BLOCK_RELEASE"):
            continue
        run_id = run.get("run_id")
        tx_path = os.path.join(runs_dir, run_id, "transcript.txt") if run_id else ""
        if run_id and os.path.isfile(tx_path):
            try:
                with open(tx_path, "r", encoding="utf-8") as f:
                    text = f.read()
                return text[-500:] if len(text) > 500 else text
            except Exception:
                pass

        notes: List[str] = []
        for category in run.get("categories", []):
            if category.get("fail_flag") or category.get("score", 5) <= 2:
                notes.append(f"{category.get('label', category.get('key', 'category'))}: {category.get('notes', '')}".strip())
        notes.extend(run.get("critical_failures", []))
        notes.extend(run.get("warnings", []))
        if notes:
            return " | ".join(notes[:3])[:500]

    for run_id in batch.get("run_ids", [])[:5]:
        tx_path = os.path.join(runs_dir, run_id, "transcript.txt")
        sc_path = os.path.join(runs_dir, run_id, "scorecard.json")
        if os.path.isfile(sc_path):
            try:
                with open(sc_path, "r", encoding="utf-8") as f:
                    sc = json.load(f)
                if sc.get("pass_fail") in ("FAIL", "FAIL_BLOCK_RELEASE"):
                    if os.path.isfile(tx_path):
                        with open(tx_path, "r", encoding="utf-8") as f:
                            text = f.read()
                        # Return last 500 chars of the transcript
                        return text[-500:] if len(text) > 500 else text
            except Exception:
                continue
    top_failures = batch.get("top_failure_categories", []) or []
    cat_avgs = batch.get("category_averages", {}) or {}
    if top_failures or cat_avgs:
        weakest = top_failures[0] if top_failures else min(cat_avgs, key=cat_avgs.get)
        weakest_score = cat_avgs.get(weakest)
        summary_bits = [f"Weakest category: {weakest}"]
        if weakest_score is not None:
            summary_bits.append(f"score={weakest_score}")
        if batch.get("average_score") is not None:
            summary_bits.append(f"batch_average={batch.get('average_score')}")
        if batch.get("pass_rate") is not None:
            summary_bits.append(f"pass_rate={batch.get('pass_rate')}")
        return " | ".join(summary_bits)
    return "No failed transcript available."


# ── Snapshot / Versioning ─────────────────────────────────────

def snapshot_persona(agent_slug: str, persona_text: str) -> str:
    """Save current persona to vault/mel/history/ before any changes."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{agent_slug}_{ts}.txt"
    path = os.path.join(HISTORY_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(persona_text)
    logger.info(f"📸 Snapshot saved: {path}")
    return path


# ── Troy Integration (Creative Lead) ──────────────────────────

def _load_agents_yaml() -> Dict[str, Any]:
    with open(AGENTS_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_agents_yaml(data: Dict[str, Any]) -> None:
    with open(AGENTS_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _find_agent_entry(agents_data: Dict[str, Any], agent_slug: str) -> Optional[Dict[str, Any]]:
    for agent in agents_data.get("agents", []):
        if agent.get("slug") == agent_slug:
            return agent
    return None


def create_persona_checkpoint(
    agent_slug: str,
    *,
    label: str = "manual",
    notes: str = "",
    source: str = "manual",
) -> Dict[str, Any]:
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
    agents_data = _load_agents_yaml()
    agent = _find_agent_entry(agents_data, agent_slug)
    if not agent:
        return {"error": f"Agent '{agent_slug}' not found in agents.yaml."}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_id = f"{agent_slug}_{ts}"
    path = os.path.join(CHECKPOINTS_DIR, f"{checkpoint_id}.json")
    payload = {
        "checkpoint_id": checkpoint_id,
        "agent_slug": agent_slug,
        "agent_name": agent.get("name", agent_slug),
        "created_at": datetime.now().isoformat(),
        "label": label,
        "source": source,
        "notes": notes,
        "persona": agent.get("persona", ""),
        "mel_patch_id": agent.get("mel_patch_id"),
        "last_improved": agent.get("last_improved"),
        "path": path,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    logger.info(f"Checkpoint saved: {path}")
    return payload


def list_persona_checkpoints(agent_slug: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    if not os.path.isdir(CHECKPOINTS_DIR):
        return []
    rows: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(CHECKPOINTS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(CHECKPOINTS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if agent_slug and data.get("agent_slug") != agent_slug:
                continue
            rows.append(data)
        except Exception:
            continue
        if len(rows) >= limit:
            break
    return rows


def restore_persona_checkpoint(checkpoint_id: str) -> Dict[str, Any]:
    path = os.path.join(CHECKPOINTS_DIR, f"{checkpoint_id}.json")
    if not os.path.isfile(path):
        return {"error": f"Checkpoint '{checkpoint_id}' not found."}

    with open(path, "r", encoding="utf-8") as f:
        checkpoint = json.load(f)

    agent_slug = checkpoint.get("agent_slug")
    if not agent_slug:
        return {"error": "Checkpoint is missing agent_slug."}

    agents_data = _load_agents_yaml()
    agent = _find_agent_entry(agents_data, agent_slug)
    if not agent:
        return {"error": f"Agent '{agent_slug}' not found in agents.yaml."}

    agent["persona"] = checkpoint.get("persona", "")
    agent["last_restored_at"] = datetime.now().isoformat()
    agent["rollback_checkpoint_id"] = checkpoint_id
    _save_agents_yaml(agents_data)

    record_lesson(
        source="mel_rollback",
        title=f"{agent_slug} restored checkpoint {checkpoint_id}",
        summary=f"Persona for {agent_slug} was restored from checkpoint {checkpoint_id}.",
        tags=["mel", "rollback", agent_slug],
        confidence=0.96,
        evidence_paths=[path],
        dedupe_key=f"rollback:{checkpoint_id}",
    )
    logger.info(f"Restored checkpoint '{checkpoint_id}' for '{agent_slug}'.")
    return {"status": "restored", "agent": agent_slug, "checkpoint_id": checkpoint_id, "path": path}


def _build_hermes_patch_brief(agent_slug: str, diagnostic: Dict[str, Any], lessons: List[Dict[str, Any]]) -> str:
    failure_category = str(diagnostic.get("failure_category", "general_performance"))
    directives: List[str] = []

    if any("false_positive_risk" in [str(tag).lower() for tag in lesson.get("tags", [])] for lesson in lessons):
        directives.append("Do not optimize for score lift alone; previous higher-scoring patches were still rejected by humans.")
    if any(
        ("loop" in str(lesson.get("title", "")).lower()) or ("repetitive" in str(lesson.get("summary", "")).lower())
        for lesson in lessons
    ):
        directives.append("Prioritize breaking repetitive fallback loops over generic tone or brevity tweaks.")
        directives.append("Do not overfit to an endless adversarial user. Prefer patches that help the agent end like a normal human once a truthful limit or realistic next step is clear.")
    if any("approved_history" in [str(tag).lower() for tag in lesson.get("tags", [])] for lesson in lessons):
        directives.append("Use previously approved behavior patterns as anchors when possible, and avoid rewriting away from them without evidence.")
    if failure_category in {"flow_naturalness", "brevity_efficiency"}:
        directives.append("Propose one structural conversation-behavior fix, not a generic tone or brevity patch.")
    if agent_slug.lower() == "amy":
        directives.append("Amy is a frontline SDR, not a security architect. Optimize for broad enterprise discovery, graceful limits, and sensible routing.")
        directives.append("Treat deep security, compliance, and proof-pressure as a minority red-team lane, not Amy's primary success case.")
        directives.append("Do not suggest a generic 'sound more natural' rewrite. Target repeated refusal loops, dead-end deferrals, and missing next-step behavior.")
        directives.append("Preserve Amy's allowed public Insight positioning and migration credibility. Do not rewrite broad cloud or CIO behavior unless the diagnostic specifically requires it.")
        directives.append("Prefer a narrow patch that gives one graceful limit plus one useful next step instead of repeated boundary phrases.")
    elif agent_slug.lower() == "evan":
        directives.append("Evan is a premium moving concierge and intake specialist for Mullins Moving. He is NOT a binding estimator, dispatcher, or scheduler.")
        directives.append("Do not propose patches that let Evan confirm appointments, promise callback timing, guarantee crew availability, or give any form of pricing.")
        directives.append("Target patches that enforce consultative intake: answer first, explain briefly, ask one meaningful question at a time, then route to estimate appointment.")
        directives.append("The only approved next steps for pricing conversations are: virtual walkthrough or in-person estimate visit. Do not add or invent alternative paths.")
        directives.append("Prefer patches that help Evan stop collecting once the inquiry is routable, rather than patches that make him sound warmer while still over-asking.")
        directives.append("Do not weaken Evan's truth boundaries. If the patch touches scheduling, availability, or pricing language, it must defer to the human team.")

    if not directives:
        return ""
    max_items = 6 if agent_slug.lower() in ("amy", "evan") else 4
    return "[HERMES PATCH BRIEF]\n" + "\n".join(f"- {item}" for item in directives[:max_items])


def generate_challengers(
    agent_config: Dict[str, Any],
    diagnostic: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Call Troy via ReviewerRunner to generate prompt patch candidates.
    Returns a list of challenger dicts: [{prompt, variant, rationale}, ...]
    """
    current_prompt = _strip_existing_mel_patches(agent_config.get("persona", ""))
    # Cap prompt injection to avoid token overflow
    if len(current_prompt) > 4000:
        current_prompt = current_prompt[:4000] + "\n[... truncated for MEL context ...]"

    agent_slug = agent_config.get("slug", "unknown")
    if agent_slug.lower() == "amy" and diagnostic.get("failure_category") == "flow_naturalness":
        graceful_boundary_patch = (
            "Amy graceful-boundary mode, critical\n"
            "Amy is a frontline SDR, not the security, compliance, or architecture owner.\n"
            "If a user asks for deep specialist detail you cannot verify, do three things only: acknowledge the concern, give one truthful high-level boundary, and offer one useful next step or routing question.\n"
            "Do not repeat the same refusal phrase across multiple turns.\n"
            "Do not answer a specialist request with another empty deferral.\n"
            "If you cannot go deeper in chat, explain why briefly in plain spoken English and redirect to what you can help with now.\n"
            "Do not invent delivery mechanics, compliance proof, documentation paths, named tools, or response-time claims.\n"
        )
        frontdoor_progression_patch = (
            "Amy front-door progression mode, critical\n"
            "Most realistic Amy conversations are broad enterprise discovery, qualification, and next-step setting.\n"
            "Prioritize one practical fit, urgency, or routing question over repeated specialist disclaimers.\n"
            "If the user already understands the limitation, move the conversation forward with one concrete next step instead of another refusal.\n"
            "Do not let the conversation collapse into an assessment-phase loop, right-team loop, or thank-you loop.\n"
            "Keep the tone commercially warm, concise, and human.\n"
        )
        return [
            {
                "variant": "graceful_boundary_mode",
                "prompt": _apply_patch(agent_config.get("persona", ""), graceful_boundary_patch, mode="lean"),
                "patch": graceful_boundary_patch,
                "rationale": "Hermes manual Amy patch: keep Amy in SDR scope while making her limits sound human and useful instead of robotic or evasive.",
                "risk_note": "If overdone, Amy could sound too cautious. Watch for replies that set a limit without still offering a practical next step.",
            },
            {
                "variant": "frontdoor_progression_mode",
                "prompt": _apply_patch(agent_config.get("persona", ""), frontdoor_progression_patch, mode="lean"),
                "patch": frontdoor_progression_patch,
                "rationale": "Hermes manual Amy patch: re-center Amy on broad enterprise discovery and forward motion instead of letting edge-case pressure dominate the conversation.",
                "risk_note": "Could become too salesy if it keeps pushing forward after a user clearly wants a boundary first. Watch for missed acknowledgment.",
            },
        ]

    # ── Evan-specific challenger generation (Mullins Moving) ──
    if agent_slug.lower() == "evan" and diagnostic.get("failure_category") in (
        "flow_naturalness", "compliance_safety", "accuracy_groundedness", "task_progression"
    ):
        consultative_boundary_patch = (
            "Evan consultative-boundary mode, critical\n"
            "Evan is a premium intake concierge, not an estimator, scheduler, or dispatcher.\n"
            "If a user pushes for pricing, dates, crew availability, or appointment confirmation, do three things only: "
            "acknowledge the request clearly, explain briefly why an accurate answer requires the proper estimate review, "
            "and offer the approved next step which is a virtual walkthrough or an in-person estimate visit.\n"
            "Do not repeat the same refusal phrase across multiple turns.\n"
            "Do not promise callback timing, appointment slots, turnaround windows, or scheduling priority.\n"
            "Do not invent handling methods, equipment, coverage specifics, or operational capabilities.\n"
            "Once the inquiry is routable, stop collecting and move to a clean handoff.\n"
        )
        estimate_routing_patch = (
            "Evan estimate-routing mode, critical\n"
            "Most realistic Evan conversations involve a prospect wanting cost guidance or an estimate.\n"
            "Prioritize routing toward one of the two approved estimate paths: virtual walkthrough or in-person estimate visit.\n"
            "Gather only the details needed to route well: name, contact, origin, destination, timing, property type, and estimate preference.\n"
            "If the user asks what the next step is, answer directly in one or two sentences and stop.\n"
            "Do not keep circling through intake questions once the move is routable.\n"
            "Do not let the conversation collapse into a repetitive explain-then-ask loop.\n"
            "Keep the tone calm, premium, and consultative. Sound like a professional who respects the caller's time.\n"
        )
        return [
            {
                "variant": "consultative_boundary_mode",
                "prompt": _apply_patch(agent_config.get("persona", ""), consultative_boundary_patch, mode="lean"),
                "patch": consultative_boundary_patch,
                "rationale": "Hermes manual Evan patch: enforce truth boundaries on pricing, scheduling, and operational promises while keeping the conversation human and useful.",
                "risk_note": "If overdone, Evan could sound evasive. Watch for replies that set a limit without still offering the estimate appointment as a concrete next step.",
            },
            {
                "variant": "estimate_routing_mode",
                "prompt": _apply_patch(agent_config.get("persona", ""), estimate_routing_patch, mode="lean"),
                "patch": estimate_routing_patch,
                "rationale": "Hermes manual Evan patch: re-center Evan on efficient estimate-appointment routing instead of letting intake loops or operational-certainty drift dominate the conversation.",
                "risk_note": "Could rush handoff if Evan skips important access or specialty-item details. Watch for missed scope signals.",
            },
        ]

    runner = ReviewerRunner(
        model="qwen2.5:14b-instruct-q6_K"
    )

    recent_lessons = []
    for lesson in reversed(load_lessons(limit=12)):
        tags = [str(tag).lower() for tag in lesson.get("tags", [])]
        if "mel" in tags or agent_slug.lower() in tags:
            recent_lessons.append(lesson)
        if len(recent_lessons) >= 3:
            break
    hermes_patch_brief = _build_hermes_patch_brief(agent_slug, diagnostic, recent_lessons)
    lessons_block = "\n".join(
        f"- {lesson.get('title', 'Lesson')}: {lesson.get('summary', '')}"
        for lesson in recent_lessons
    ) or "No prior MEL lessons recorded."

    inputs = {
        "agent_name": agent_config.get("name", agent_config.get("slug", "unknown")),
        "current_prompt": current_prompt,
        "role_review": (
            f"FAILURE CATEGORY: {diagnostic['failure_category']}\n"
            f"FAILURE RATE: {diagnostic['failure_rate']}%\n"
            f"FAILED EXCHANGE SNIPPET:\n{diagnostic['failed_exchange']}"
        ),
        "conversation_review": (
            f"Baseline score: {diagnostic['baseline_score']}. Pass rate: {diagnostic['baseline_pass_rate']}%.\n"
            f"Relevant Hermes lessons:\n{lessons_block}\n"
            f"{hermes_patch_brief}"
        ),
        "safety_review": "No safety issues detected.",
        "failure_category": diagnostic["failure_category"],
        "failure_rate": str(diagnostic["failure_rate"]),
        "failed_exchange": diagnostic["failed_exchange"],
    }

    logger.info(f"🧠 Calling Troy for patch candidates on '{inputs['agent_name']}'...")
    result = runner.run_reviewer(TROY_CONFIG, inputs)

    if result.get("status") == "error":
        error_msg = result.get("error", "Unknown Troy error")
        logger.error(f"Troy failed: {error_msg}")
        # Bubble error to Hub
        emit_progress("troy", "error", f"❌ Troy failed: {error_msg}", 50, agent_config.get("slug"))
        return []

    # Extract patch candidate(s) from Troy's response
    challengers = []
    patch_text = result.get("patch_candidate", "")
    rationale = result.get("rationale", "")
    risk = result.get("risk_note", "")
    thinking = result.get("thinking", "")

    # Prepend thinking to rationale if user wants visibility
    full_rationale = rationale
    if thinking:
        full_rationale = f"### [TROY THINKING]\n{thinking}\n\n### [RATIONALE]\n{rationale}"

    if patch_text:
        # Generate Lean variant (the patch as-is)
        lean_prompt = _apply_patch(agent_config.get("persona", ""), patch_text, mode="lean")
        challengers.append({
            "variant": "lean",
            "prompt": lean_prompt,
            "patch": patch_text,
            "rationale": full_rationale,
            "risk_note": risk,
        })

        # Generate Strict variant (patch + tighter guardrails)
        strict_prompt = _apply_patch(agent_config.get("persona", ""), patch_text, mode="strict")
        challengers.append({
            "variant": "strict",
            "prompt": strict_prompt,
            "patch": patch_text,
            "rationale": full_rationale + "\n\n[STRICT: Added reinforced constraints.]",
            "risk_note": risk,
        })

    logger.info(f"✅ Troy generated {len(challengers)} challenger(s).")
    return challengers


def _strip_existing_mel_patches(prompt_text: str) -> str:
    """Remove previously appended MEL patch tails so challengers stay clean."""
    if not prompt_text:
        return ""
    marker = "\n\n### [MEL PATCH"
    first_marker = prompt_text.find(marker)
    if first_marker != -1:
        return prompt_text[:first_marker].rstrip()
    return prompt_text.rstrip()


def _apply_patch(original: str, patch: str, mode: str = "lean") -> str:
    """
    Apply Troy's patch to the original prompt.
    Lean: Append the patch.
    Strict: Append patch + add reinforcement guardrail.
    """
    cleaned_original = _strip_existing_mel_patches(original)
    patched = f"{cleaned_original}\n\n### [MEL PATCH — {mode.upper()}]\n{patch}"
    if mode == "strict":
        patched += (
            "\n\n### [REINFORCED CONSTRAINTS]\n"
            "- STRICTLY adhere to the patched instructions above.\n"
            "- Do NOT revert to previous behavior patterns.\n"
            "- Prioritize the patched behavior in all edge cases."
        )
    return patched


def _record_mel_cycle_lesson(
    *,
    agent_slug: str,
    diagnostic: Dict[str, Any],
    baseline_result: Dict[str, Any],
    best_challenger: Dict[str, Any],
    improvement: float,
    pending_id: str,
    snapshot_path: str,
) -> None:
    failure_category = diagnostic.get("failure_category", "general_performance")
    baseline_score = baseline_result.get("score", 0)
    challenger_score = best_challenger.get("score", 0)
    lesson_title = f"{agent_slug} MEL cycle {pending_id}"
    lesson_summary = (
        f"Weakest area was {failure_category}. Baseline scored {baseline_score}, best challenger scored {challenger_score}, "
        f"for an improvement of {improvement:+.1f}. Treat this as review-stage evidence, not automatic truth, until a human approves or rejects the patch."
    )
    record_lesson(
        source="mel",
        title=lesson_title,
        summary=lesson_summary,
        tags=["mel", agent_slug, failure_category],
        confidence=0.7 if improvement > 0 else 0.58,
        evidence_paths=[
            snapshot_path,
            os.path.join(PENDING_DIR, f"{pending_id}.json"),
        ],
    )


# ── Batch Evaluation ──────────────────────────────────────────

async def evaluate_prompt(
    agent_slug: str,
    prompt_text: str,
    scenario_pack: str,
    scenarios: List[Dict[str, Any]],
    max_turns: int,
    scoring_rubric: str = "default_v1",
    stage_name: str = "eval",
    base_pct: int = 0,
    batch_manifest: Optional[Dict[str, Any]] = None,
    batch_manifest_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run batch eval using ONLY text-to-text sim (Ollama).
    Zero Anam tokens. Zero browser. Zero CDP.
    """
    # Limitless handling: cap at 15 turns for safety (Circuit Breaker)
    is_limitless = (max_turns == 0)
    effective_turns = 15 if is_limitless else max_turns

    num_scenarios = len(scenarios)
    inputs = EvalInputs(
        target_agent=agent_slug,
        environment="sim",              # HARDCODED: sim only
        scenario_pack=scenario_pack,
        scoring_rubric=scoring_rubric,
        runs=num_scenarios,
        browser_mode=False,             # HARDCODED: no browser
        save_screenshots=False,         # HARDCODED: no screenshots
        override_prompt=prompt_text,    # Use the challenger prompt
        max_turns=effective_turns,
        limitless=is_limitless,
        transcript_mode="ollama_sim",   # HARDCODED: text-to-text
        scenario_pack_class=(
            "adaptive"
            if any((scenario.get("pack_class") == "adaptive") for scenario in scenarios)
            else "core"
        ),
        scenario_manifest_id=(batch_manifest or {}).get("manifest_id"),
        scenario_manifest_path=batch_manifest_path,
    )
    if not scenarios:
        return {"error": "No scenarios found", "score": 0, "pass_rate": 0}

    batch_id = f"mel_{uuid.uuid4().hex[:8]}"
    batch_started_at = datetime.now()
    scorecards = []
    run_ids = []
    logged_turns: Dict[Tuple[int, int], Tuple[str, str]] = {}

    for i, scenario in enumerate(scenarios):
        run_id = f"mel_run_{uuid.uuid4().hex[:8]}"
        run_ids.append(run_id)

        # Emit intra-stage progress
        progress_pct = base_pct + int((i / num_scenarios) * 10)
        
        # Turn callback for better Hub transparency during long runs
        def on_turn_cb(turn_num, user_msg, agent_reply):
            # Use 50 turns as reference if limitless, otherwise inputs.max_turns
            ref_turns = 50 if inputs.limitless else inputs.max_turns
            turn_pct = progress_pct + int((turn_num / ref_turns) * (10 / num_scenarios))
            
            user_text = (user_msg or "").strip()
            agent_text = (agent_reply or "").strip()

            # Log only completed turns to keep session transcripts clean.
            if session_logger and agent_text:
                turn_key = (i + 1, turn_num)
                previous = logged_turns.get(turn_key)
                current = (user_text, agent_text)
                if previous != current:
                    logged_turns[turn_key] = current
                    session_logger.log(f"[Scenario {i+1}] Turn {turn_num}:")
                    session_logger.log(f"  User: {user_text}")
                    session_logger.log(f"  Agent: {agent_text}")

            # Emit structured data for Live Hub View
            data = {
                "turn": turn_num,
                "scenario": i + 1,
                "user": user_msg,
                "agent_msg": agent_reply
            }
            emit_progress(stage_name, "active", f"Scenario {i+1}: Turn {turn_num}", turn_pct, agent_slug, data)

        def on_status_cb(status_name, payload):
            if status_name == "scoring_start":
                emit_progress(
                    stage_name,
                    "active",
                    f"Scenario {i+1}: Scoring",
                    min(progress_pct + 1, base_pct + 9),
                    agent_slug,
                    {"scenario": i + 1, "phase": "scoring_start"},
                )
                return
            if status_name == "scoring_category_start":
                cat_idx = payload.get("category_index", 0)
                cat_total = payload.get("category_total", 0)
                emit_progress(
                    stage_name,
                    "active",
                    f"Scenario {i+1}: Scoring {cat_idx}/{cat_total}",
                    min(progress_pct + 1, base_pct + 9),
                    agent_slug,
                    {
                        "scenario": i + 1,
                        "phase": "scoring",
                        "category_index": cat_idx,
                        "category_total": cat_total,
                        "category_key": payload.get("category_key"),
                    },
                )
                return
            if status_name == "scoring_done":
                emit_progress(
                    stage_name,
                    "active",
                    f"Scenario {i+1}: Scored",
                    min(progress_pct + 2, base_pct + 9),
                    agent_slug,
                    {
                        "scenario": i + 1,
                        "phase": "scoring_done",
                        "overall_score": payload.get("overall_score"),
                        "pass_fail": payload.get("pass_fail"),
                    },
                )
                return
            if status_name == "scoring_error":
                emit_progress(
                    stage_name,
                    "error",
                    f"Scenario {i+1}: Scoring error",
                    min(progress_pct + 2, base_pct + 9),
                    agent_slug,
                    {
                        "scenario": i + 1,
                        "phase": "scoring_error",
                        "error": payload.get("error"),
                    },
                )
            
        metadata, transcript, scorecard = await execute_simulated_run(
            run_id=run_id,
            batch_id=batch_id,
            inputs=inputs,
            scenario=scenario,
            on_turn=on_turn_cb,
            on_status=on_status_cb,
        )

        if scorecard:
            scorecards.append(scorecard)
            save_run_artifacts(run_id, batch_id, metadata, transcript, scorecard)

    # Aggregate
    summary = aggregate_batch(batch_id, inputs, scorecards, run_ids)
    if batch_manifest:
        summary.data["batch_manifest"] = batch_manifest
        summary.data["scenario_source_counts"] = batch_manifest.get("source_counts", {})
        summary.data["pack_class_counts"] = batch_manifest.get("pack_class_counts", {})
    save_batch_artifacts(batch_id, summary)
    batch_ended_at = datetime.now()
    record_workflow_run(
        workflow="mel_batch_eval",
        run_id=batch_id,
        status=summary.verdict.lower(),
        started_at=batch_started_at,
        ended_at=batch_ended_at,
        metadata={
            "agent": agent_slug,
            "scenario_pack": scenario_pack,
            "stage_name": stage_name,
            "average_score": summary.average_score,
            "pass_rate": summary.pass_rate,
            "total_runs": summary.total_runs,
        },
    )
    capture_gpu_sample(
        workflow="mel_batch_eval",
        run_id=batch_id,
        metadata={"agent": agent_slug, "stage_name": stage_name},
    )

    return {
        "batch_id": batch_id,
        "scenario_pack_class": inputs.scenario_pack_class,
        "scenario_manifest_id": inputs.scenario_manifest_id,
        "scenario_manifest_path": inputs.scenario_manifest_path,
        "scenario_source_counts": (batch_manifest or {}).get("source_counts", {}),
        "pack_class_counts": (batch_manifest or {}).get("pack_class_counts", {}),
        "runtime_failure_count": summary.data.get("runtime_failure_count", 0),
        "score": summary.average_score,
        "pass_rate": summary.pass_rate,
        "verdict": summary.verdict,
        "category_averages": summary.category_averages,
        "total_runs": summary.total_runs,
        "passed": summary.passed,
        "failed": summary.failed,
    }


# ── Pending Approval System ──────────────────────────────────

def save_pending(
    agent_slug: str,
    diagnostic: Dict[str, Any],
    baseline_result: Dict[str, Any],
    challengers: List[Dict[str, Any]],
    challenger_results: List[Dict[str, Any]],
    snapshot_path: str,
) -> str:
    """Save evolution results to vault/mel/pending/ for human approval."""
    os.makedirs(PENDING_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pending_id = f"{agent_slug}_{ts}"
    path = os.path.join(PENDING_DIR, f"{pending_id}.json")

    # Find the best challenger
    best_idx = 0
    best_score = 0
    for i, result in enumerate(challenger_results):
        if result.get("score", 0) > best_score:
            best_score = result.get("score", 0)
            best_idx = i

    winner = challengers[best_idx] if challengers else None
    baseline_score = baseline_result.get("score", 0)
    improvement = round(best_score - baseline_score, 1)
    has_recommended_patch = bool(winner) and improvement > 0
    baseline_runtime_failures = baseline_result.get("runtime_failure_count", 0)
    challenger_runtime_failures = sum(result.get("runtime_failure_count", 0) for result in challenger_results)
    total_runtime_failures = baseline_runtime_failures + challenger_runtime_failures

    if total_runtime_failures:
        recommendation = {
            "variant": "runtime_failure",
            "prompt": "",
            "patch": "",
            "rationale": "This MEL cycle hit runtime failures or model timeouts, so the scores are not trustworthy enough for persona approval.",
            "score": baseline_score,
            "improvement": 0,
            "passes_threshold": False,
        }
    elif has_recommended_patch:
        recommendation = {
            "variant": winner.get("variant"),
            "prompt": winner.get("prompt"),
            "patch": winner.get("patch"),
            "rationale": winner.get("rationale"),
            "score": best_score,
            "improvement": improvement,
            "passes_threshold": improvement >= 10,
        }
    else:
        recommendation = {
            "variant": "baseline",
            "prompt": "",
            "patch": "",
            "rationale": "Baseline outperformed or matched all challengers. No candidate patch is recommended for approval.",
            "score": baseline_score,
            "improvement": improvement,
            "passes_threshold": False,
        }

    pending = {
        "pending_id": pending_id,
        "agent_slug": agent_slug,
        "created_at": datetime.now().isoformat(),
        "snapshot_path": snapshot_path,
        "scenario_manifest_id": baseline_result.get("scenario_manifest_id"),
        "scenario_manifest_path": baseline_result.get("scenario_manifest_path"),
        "scenario_source_counts": baseline_result.get("scenario_source_counts", {}),
        "pack_class_counts": baseline_result.get("pack_class_counts", {}),
        "runtime_failure_count": total_runtime_failures,
        "status": "pending",  # pending | approved | rejected
        "diagnostic": diagnostic,
        "baseline": baseline_result,
        "challengers": [
            {
                "variant": c.get("variant"),
                "patch": c.get("patch"),
                "rationale": c.get("rationale"),
                "risk_note": c.get("risk_note"),
                "result": r,
            }
            for c, r in zip(challengers, challenger_results)
        ],
        "recommendation": recommendation,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

    logger.info(f"📋 Pending approval saved: {path}")
    return pending_id


def load_pending_approvals() -> List[Dict[str, Any]]:
    """Load all pending approval files."""
    if not os.path.isdir(PENDING_DIR):
        return []
    approvals = []
    for fname in sorted(os.listdir(PENDING_DIR), reverse=True):
        if fname.endswith(".json"):
            path = os.path.join(PENDING_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == "pending":
                    approvals.append(data)
            except Exception:
                continue
    return approvals


def apply_approval(pending_id: str) -> Dict[str, Any]:
    """Apply the approved prompt patch to agents.yaml."""
    path = os.path.join(PENDING_DIR, f"{pending_id}.json")
    if not os.path.isfile(path):
        return {"error": f"Pending ID '{pending_id}' not found."}

    with open(path, "r", encoding="utf-8") as f:
        pending = json.load(f)

    if pending.get("status") != "pending":
        return {"error": f"Already processed: {pending.get('status')}"}

    agent_slug = pending["agent_slug"]
    new_prompt = pending["recommendation"]["prompt"]

    if not new_prompt:
        # Safely resolve baseline/empty-prompt packets without modifying agents.yaml
        pending["status"] = "resolved_baseline"
        pending["resolved_at"] = datetime.now().isoformat()
        pending["resolution_note"] = "No prompt patch to apply. Baseline was retained. Packet cleared from queue."
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)

        record_lesson(
            source="mel_review",
            title=f"{agent_slug} resolved baseline packet {pending_id}",
            summary=f"Human resolved a baseline/empty-prompt MEL packet for {agent_slug}. No persona change was applied.",
            tags=["mel", "resolved_baseline", agent_slug],
            confidence=0.90,
            evidence_paths=[path],
        )

        logger.info(f"✅ Resolved baseline packet '{pending_id}' for '{agent_slug}' (no persona change).")
        return {
            "status": "resolved_baseline",
            "agent": agent_slug,
            "pending_id": pending_id,
            "note": "Baseline retained. No prompt patch was applied.",
        }

    checkpoint = create_persona_checkpoint(
        agent_slug,
        label="pre_apply_approval",
        notes=f"Automatic rollback checkpoint before applying {pending_id}.",
        source="mel_approval",
    )
    if "error" in checkpoint:
        return checkpoint

    # Update agents.yaml
    agents_data = _load_agents_yaml()

    updated = False
    agent = _find_agent_entry(agents_data, agent_slug)
    if agent:
        agent["persona"] = new_prompt
        agent["last_improved"] = datetime.now().isoformat()
        agent["mel_patch_id"] = pending_id
        agent["last_checkpoint_id"] = checkpoint.get("checkpoint_id")
        updated = True

    if not updated:
        return {"error": f"Agent '{agent_slug}' not found in agents.yaml."}

    _save_agents_yaml(agents_data)

    # Mark as approved
    pending["status"] = "approved"
    pending["approved_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

    record_lesson(
        source="mel_review",
        title=f"{agent_slug} approved patch {pending_id}",
        summary=(
            f"Human approved the MEL recommendation for {agent_slug}. "
            f"Recommended variant: {pending.get('recommendation', {}).get('variant', 'unknown')}."
        ),
        tags=["mel", "approval", agent_slug],
        confidence=0.92,
        evidence_paths=[path],
    )

    logger.info(f"✅ Approved and applied patch '{pending_id}' to '{agent_slug}'.")
    return {
        "status": "approved",
        "agent": agent_slug,
        "pending_id": pending_id,
        "rollback_checkpoint_id": checkpoint.get("checkpoint_id"),
    }


def reject_approval(pending_id: str) -> Dict[str, Any]:
    """Reject a pending prompt patch."""
    path = os.path.join(PENDING_DIR, f"{pending_id}.json")
    if not os.path.isfile(path):
        return {"error": f"Pending ID '{pending_id}' not found."}

    with open(path, "r", encoding="utf-8") as f:
        pending = json.load(f)

    pending["status"] = "rejected"
    pending["rejected_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

    record_lesson(
        source="mel_review",
        title=f"{pending.get('agent_slug', 'agent')} rejected patch {pending_id}",
        summary="Human rejected the MEL recommendation. Treat the candidate patch as unreliable for future cycles unless later evidence supports it.",
        tags=["mel", "rejection", pending.get("agent_slug", "agent")],
        confidence=0.95,
        evidence_paths=[path],
    )

    logger.info(f"❌ Rejected patch '{pending_id}'.")
    return {"status": "rejected", "pending_id": pending_id}


async def run_evolution(
    agent_slug: str,
    scenario_pack: str = "default_pack",
    num_scenarios: int = 3,
    max_turns: int = 8,
    difficulty: str = "mixed",
) -> Dict[str, Any]:
    """Main Evolution Loop."""
    # Reset progress at start
    reset_progress()
    register_session()
    run_started_at = datetime.now()
    evolution_run_id = f"mel_evolution_{uuid.uuid4().hex[:8]}"
    
    try:
        # Initialize forensic session logger
        global session_logger
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_logger = SessionLogger(session_id)
        session_logger.log(f"Starting MEL Evolution Loop for agent: {agent_slug}")

        logger.info(f"🦸 MEL EVOLUTION LOOP — Agent: {agent_slug}")
        logger.info(f"{'='*60}")

        # ── 0. Surgical Pack Discovery ──────────────────
        if scenario_pack == "default_pack":
            scenario_pack = resolve_mel_scenario_pack(
                agent_slug=agent_slug,
                requested_pack=scenario_pack,
                difficulty=difficulty,
            )

        emit_progress("preflight", "active", "🔌 Checking Ollama connection...", 5, agent_slug)
        capture_gpu_sample(
            workflow="mel_evolution",
            run_id=evolution_run_id,
            metadata={"agent": agent_slug, "phase": "start"},
        )
    
        # 1. Pre-flight
        if not preflight_check():
            emit_progress("preflight", "error", "❌ Ollama is not running. Aborting.", 5, agent_slug)
            return {"error": "Ollama is not running. Aborting."}
        emit_progress("preflight", "done", "✅ Ollama is online.", 10, agent_slug)
    
        # 2. Load agent
        emit_progress("load_agent", "active", f"Loading agent config for '{agent_slug}'...", 12, agent_slug)
        try:
            agent_config = load_agent_config(agent_slug)
        except ValueError as e:
            emit_progress("load_agent", "error", str(e), 12, agent_slug)
            return {"error": str(e)}
    
        current_persona = agent_config.get("persona", "")
        if not current_persona:
            emit_progress("load_agent", "error", f"Agent '{agent_slug}' has no persona.", 12, agent_slug)
            return {"error": f"Agent '{agent_slug}' has no persona in agents.yaml."}
        eval_default_pack, eval_default_rubric = resolve_agent_eval_defaults(agent_config)
        scenario_pack = resolve_mel_scenario_pack(
            agent_slug=agent_slug,
            requested_pack=scenario_pack,
            difficulty=difficulty,
            agent_config=agent_config,
        )
        scoring_rubric = eval_default_rubric or ("director_v1" if agent_slug.lower() == "dani" else "default_v1")
        emit_progress("load_agent", "done", f"Loaded '{agent_config.get('name', agent_slug)}' persona. Pack: {scenario_pack}", 15, agent_slug)
    
        # 3. Snapshot
        emit_progress("snapshot", "active", "📸 Snapshotting for rollback...", 18, agent_slug)
        snapshot_path = snapshot_persona(agent_slug, current_persona)
        emit_progress("snapshot", "done", "✅ Persona snapshot saved.", 20, agent_slug)
    
        # 4. Build a MEL 2.0 batch with canonical + Hermes adaptive coverage
        emit_progress("baseline", "active", f"Planning {num_scenarios} MEL 2.0 scenarios from '{scenario_pack}'...", 22, agent_slug)
        scenarios, batch_manifest = build_batch_plan(
            agent_slug=agent_slug,
            scenario_pack=scenario_pack,
            difficulty=difficulty,
            count=num_scenarios,
        )
        batch_manifest_path = persist_batch_manifest(batch_manifest)
        if not scenarios:
            emit_progress("baseline", "error", "No scenarios found in pack.", 22, agent_slug)
            return {"error": "No scenarios were found to test against."}
        emit_progress(
            "baseline",
            "active",
            (
                f"Prepared {batch_manifest.get('source_counts', {}).get('canonical', 0)} core and "
                f"{batch_manifest.get('source_counts', {}).get('hermes_adaptive', 0)} adaptive scenarios."
            ),
            24,
            agent_slug,
            {"batch_manifest_id": batch_manifest.get("manifest_id"), "manifest_path": batch_manifest_path},
        )
    
        # 5. Run baseline eval
        baseline_result = await evaluate_prompt(
            agent_slug=agent_slug,
            prompt_text=current_persona,
            scenario_pack=scenario_pack,
            scenarios=scenarios,
            max_turns=max_turns,
            scoring_rubric=scoring_rubric,
            stage_name="baseline",
            base_pct=25,
            batch_manifest=batch_manifest,
            batch_manifest_path=batch_manifest_path,
        )
        logger.info(f"📊 Baseline: Score={baseline_result.get('score')}, Pass Rate={baseline_result.get('pass_rate')}%")
        emit_progress("baseline", "done",
            f"Baseline: Score={baseline_result.get('score')}%, Pass Rate={baseline_result.get('pass_rate')}%",
            35, agent_slug, {"score": baseline_result.get("score"), "pass_rate": baseline_result.get("pass_rate")})
    
        # 5. Diagnose (Sloane's role — now uses baseline results)
        emit_progress("diagnose", "active", "🔍 Sloane analyzing baseline performance...", 40, agent_slug)
        diagnostic = extract_diagnostic(agent_slug, batch_data=baseline_result)
        logger.info(f"🔍 Diagnostic: Weakest category = '{diagnostic['failure_category']}' "
                    f"({diagnostic['failure_rate']}% failure rate)")
        emit_progress("diagnose", "done",
            f"Weakest: {diagnostic['failure_category']} ({diagnostic['failure_rate']}% failure rate)",
            45, agent_slug, {"failure_category": diagnostic["failure_category"], "failure_rate": diagnostic["failure_rate"]})
    
        # 6. Generate challengers (Troy's role)
        emit_progress("troy", "active", "🧠 Troy generating prompt patches...", 50, agent_slug)
        challengers = generate_challengers(agent_config, diagnostic)
        if not challengers:
            emit_progress("troy", "error", "❌ Troy failed to generate challengers.", 50, agent_slug)
            return {"error": "Troy failed to generate challenger prompts.", "diagnostic": diagnostic}
        emit_progress("troy", "done", f"✅ Troy generated {len(challengers)} challenger(s) (Lean + Strict).", 60, agent_slug)
    
        # 7. Run challenger evals
        challenger_results = []
        for i, challenger in enumerate(challengers):
            base_pct = 65 + (i * 15)
            result = await evaluate_prompt(
                agent_slug=agent_slug,
                prompt_text=challenger["prompt"],
                scenario_pack=scenario_pack,
                scenarios=scenarios,
                max_turns=max_turns,
                scoring_rubric=scoring_rubric,
                stage_name=f"challenger_{i+1}",
                base_pct=base_pct,
                batch_manifest=batch_manifest,
                batch_manifest_path=batch_manifest_path,
            )
            challenger_results.append(result)
            logger.info(f"⚔️  Challenger {i+1}: Score={result.get('score')}, "
                        f"Pass Rate={result.get('pass_rate')}%")
            emit_progress(f"challenger_{i+1}", "done",
                f"Challenger {i+1} ({challenger['variant']}): Score={result.get('score')}%, Pass Rate={result.get('pass_rate')}%",
                base_pct + 10, agent_slug, {"variant": challenger["variant"], "score": result.get("score"), "pass_rate": result.get("pass_rate")})
    
        # 8. Save to pending (NO auto-promotion)
        emit_progress("saving", "active", "📋 Saving results for your approval...", 92, agent_slug)
        pending_id = save_pending(
            agent_slug=agent_slug,
            diagnostic=diagnostic,
            baseline_result=baseline_result,
            challengers=challengers,
            challenger_results=challenger_results,
            snapshot_path=snapshot_path,
        )
    
        # 9. Summary
        best_challenger = max(challenger_results, key=lambda r: r.get("score", 0))
        improvement = round(best_challenger.get("score", 0) - baseline_result.get("score", 0), 1)
    
        emit_progress("complete", "done",
            f"🏁 Complete! Baseline: {baseline_result.get('score', 0)}% → Best: {best_challenger.get('score', 0)}% ({'+' if improvement > 0 else ''}{improvement}%). Awaiting your approval.",
            100, agent_slug, {
                "baseline_score": baseline_result.get("score", 0),
                "best_score": best_challenger.get("score", 0),
                "improvement": improvement,
                "pending_id": pending_id,
            })
    
        summary = {
            "status": "complete",
            "pending_id": pending_id,
            "agent": agent_slug,
            "batch_manifest_id": batch_manifest.get("manifest_id"),
            "batch_manifest_path": batch_manifest_path,
            "baseline_score": baseline_result.get("score", 0),
            "best_challenger_score": best_challenger.get("score", 0),
            "improvement": improvement,
            "recommendation": "APPROVE" if improvement >= 10 else "REVIEW",
            "diagnostic": diagnostic,
            "awaiting_approval": True,
        }
    
        logger.info(f"\n{'='*60}")
        logger.info(f"🏁 MEL COMPLETE — {agent_slug}")
        logger.info(f"   Baseline:       {baseline_result.get('score', 0)}%")
        logger.info(f"   Best Challenger: {best_challenger.get('score', 0)}%")
        logger.info(f"   Improvement:     {'+' if improvement > 0 else ''}{improvement}%")
        logger.info(f"   Recommendation:  {'✅ APPROVE' if improvement >= 10 else '🔍 REVIEW'}")
        logger.info(f"   Pending ID:      {pending_id}")
        logger.info(f"   ⏳ Awaiting your approval in the Hub.")
        logger.info(f"{'='*60}\n")
        _record_mel_cycle_lesson(
            agent_slug=agent_slug,
            diagnostic=diagnostic,
            baseline_result=baseline_result,
            best_challenger=best_challenger,
            improvement=improvement,
            pending_id=pending_id,
            snapshot_path=snapshot_path,
        )

        run_ended_at = datetime.now()
        record_workflow_run(
            workflow="mel_evolution",
            run_id=evolution_run_id,
            status="complete",
            started_at=run_started_at,
            ended_at=run_ended_at,
            metadata={
                "agent": agent_slug,
                "scenario_pack": scenario_pack,
                "batch_manifest_id": batch_manifest.get("manifest_id"),
                "batch_manifest_path": batch_manifest_path,
                "baseline_score": baseline_result.get("score", 0),
                "best_challenger_score": best_challenger.get("score", 0),
                "improvement": improvement,
                "pending_id": pending_id,
            },
        )
        capture_gpu_sample(
            workflow="mel_evolution",
            run_id=evolution_run_id,
            metadata={"agent": agent_slug, "phase": "complete"},
        )
        return summary
    finally:
        if "baseline_result" not in locals():
            record_workflow_run(
                workflow="mel_evolution",
                run_id=evolution_run_id,
                status="error",
                started_at=run_started_at,
                ended_at=datetime.now(),
                metadata={"agent": agent_slug},
            )
        cleanup_session()


# ── CLI Entry Point ───────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MEL Superhero Agent — Evolution Engine")
    parser.add_argument("--agent", required=True, help="Agent slug (e.g., amy, morgan)")
    parser.add_argument("--pack", default="default_pack", help="Scenario pack")
    parser.add_argument("--scenarios", type=int, default=3, help="Number of scenarios per eval")
    parser.add_argument("--turns", type=int, default=8, help="Max turns per scenario")
    parser.add_argument("--difficulty", default="mixed", help="Scenario difficulty")
    args = parser.parse_args()

    result = asyncio.run(run_evolution(
        agent_slug=args.agent,
        scenario_pack=args.pack,
        num_scenarios=args.scenarios,
        max_turns=args.turns,
        difficulty=args.difficulty,
    ))
    sys.stdout.write(json.dumps(result, indent=2))
