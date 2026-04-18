import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from tools.hermes_memory import (
    build_operational_memory_brief,
    get_hermes_memory_snapshot,
    record_lesson,
    remember_mission_state,
    remember_operator_action,
    remember_rollback_checkpoint,
)


def _now() -> str:
    return datetime.now().isoformat()


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return cleaned or "general_chat"


def _infer_intent(request: str, context: Optional[Dict[str, Any]] = None) -> str:
    text = (request or "").strip().lower()
    hint = str((context or {}).get("intent_hint") or "").strip().lower()
    if hint:
        return hint
    if any(token in text for token in ("run a ", "launch a ", "start a ", "test operator", "sh lab", "x agent eval", "x-agent eval")):
        return "test_session_create"
    if any(token in text for token in ("status of", "check status", "mission status")) and "job" in text:
        return "test_session_status"
    if any(token in text for token in ("show report", "mission report", "test-session digest", "summarize test sessions")):
        return "test_session_report"
    if any(token in text for token in ("approve email", "send report", "email report")):
        return "test_session_email"
    if "reply" in text and "email" in text:
        return "founder_email_reply"
    if re.search(r"https?://", text):
        return "browser_scout"
    if any(token in text for token in ("briefing", "brief")):
        return "briefing"
    if any(token in text for token in ("sync", "audit")):
        return "ops_command"
    return "general_chat"


def _step_template(intent: str) -> List[Dict[str, Any]]:
    if intent == "test_session_create":
        return [
            {"key": "preflight", "label": "Preflight", "status": "pending"},
            {"key": "sh_lab", "label": "SH Lab", "status": "pending"},
            {"key": "xagent_eval", "label": "X-Agent Eval", "status": "pending"},
            {"key": "report", "label": "Report", "status": "pending"},
            {"key": "email", "label": "Dispatch", "status": "pending"},
        ]
    if intent in {"test_session_status", "test_session_report", "test_session_email"}:
        return [
            {"key": "locate", "label": "Locate Mission", "status": "pending"},
            {"key": "inspect", "label": "Inspect State", "status": "pending"},
            {"key": "respond", "label": "Respond", "status": "pending"},
        ]
    return [
        {"key": "interpret", "label": "Interpret Request", "status": "pending"},
        {"key": "respond", "label": "Respond", "status": "pending"},
    ]


def _match_memory_links(intent: str) -> List[str]:
    snapshot = get_hermes_memory_snapshot()
    links: List[str] = []
    for lesson in snapshot.get("recent_lessons", []):
        tags = [str(tag).lower() for tag in lesson.get("tags", [])]
        if intent in tags or intent.replace("_", " ") in str(lesson.get("summary", "")).lower():
            links.extend(lesson.get("evidence_paths", []))
    seen = []
    for link in links:
        if link and link not in seen:
            seen.append(link)
    return seen[:5]


def plan_operator_mission(request: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    context = context or {}
    intent = _infer_intent(request, context)
    target_agent = str(context.get("target_agent") or context.get("owner_agent") or "hermes").strip().lower()
    mission_id = str(context.get("mission_id") or f"hermes_{intent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    plan_steps = _step_template(intent)
    risky = intent in {"test_session_create", "test_session_email", "ops_command"}
    rollback_checkpoint = {
        "recommended": risky,
        "reason": "Long-running or outbound mission" if risky else "No rollback checkpoint required",
    }
    plan = {
        "mission_id": mission_id,
        "requested_by": str(context.get("requested_by") or "Rob"),
        "owner_agent": "hermes",
        "persona": str(context.get("persona") or "sloane"),
        "target_agent": target_agent,
        "request": request,
        "intent": intent,
        "status": "planned",
        "active_step": plan_steps[0]["key"] if plan_steps else None,
        "plan_steps": plan_steps,
        "artifacts": {},
        "memory_links": _match_memory_links(intent),
        "rollback_checkpoint": rollback_checkpoint,
        "metadata": {
            "source": str(context.get("source") or "bridge"),
            "conversation_length": len(context.get("chat_history") or []),
            "intent_key": _slugify(intent),
        },
    }
    remember_operator_action(
        "plan_operator_mission",
        {
            "mission_id": mission_id,
            "intent": intent,
            "target_agent": target_agent,
        },
    )
    return plan


def normalize_job_to_mission(job: Dict[str, Any]) -> Dict[str, Any]:
    spec = job.get("spec") or {}
    steps = job.get("steps") or {}
    plan_steps = []
    active_step = None
    for key, step in steps.items():
        status = str(step.get("status") or "pending")
        if active_step is None and status in {"running", "pending", "queued"}:
            active_step = key
        plan_steps.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "status": status,
                "updated_at": step.get("updated_at"),
            }
        )

    release = job.get("results", {}).get("release_readiness") or {}
    rollback_checkpoint = release.get("rollback_checkpoint") or {
        "recommended": False,
        "reason": "No rollback checkpoint recorded yet",
    }
    mission = {
        "mission_id": job.get("job_id"),
        "job_id": job.get("job_id"),
        "owner_agent": "hermes",
        "requested_by": "Rob",
        "intent": "test_session_create",
        "plan_steps": plan_steps,
        "active_step": active_step or (plan_steps[-1]["key"] if plan_steps else None),
        "status": job.get("phase") or job.get("status") or "unknown",
        "artifacts": job.get("artifacts", {}),
        "memory_links": [path for path in job.get("artifacts", {}).values() if isinstance(path, str) and path],
        "rollback_checkpoint": rollback_checkpoint,
        "legacy_job": job,
        "phase": job.get("phase"),
        "spec": spec,
        "steps": steps,
        "results": job.get("results", {}),
        "errors": job.get("errors", []),
    }
    return mission


def execute_operator_plan(plan: Dict[str, Any], runtime_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    runtime_context = runtime_context or {}
    intent = str(plan.get("intent") or "general_chat")
    args = runtime_context.get("args") or {}

    if intent == "test_session_create":
        from tools.sloane_jobs import create_test_operator_job, start_job

        mission_request = str(args.get("request") or plan.get("request") or "").strip()
        job = create_test_operator_job(mission_request, args)
        if runtime_context.get("start", True):
            job = start_job(job["job_id"])
        mission = normalize_job_to_mission(job)
        remember_mission_state(mission)
        if mission.get("rollback_checkpoint", {}).get("recommended"):
            remember_rollback_checkpoint({"mission_id": mission["mission_id"], "status": mission["status"]})
        return {
            "status": "running",
            "intent": intent,
            "job_id": job["job_id"],
            "job": job,
            "mission": mission,
            "reply_hint": f"Mission dispatched. Test Operator job {job['job_id']} is now {job['phase']} for {job['spec']['target_agent']}.",
        }

    if intent == "test_session_status":
        from tools.sloane_jobs import list_jobs, load_job

        job_id = args.get("job_id")
        job = load_job(job_id) if job_id else (list_jobs(limit=1)[0] if list_jobs(limit=1) else None)
        if not job:
            return {"status": "not_found", "intent": intent, "reply_hint": "No Sloane test operator job is currently on record."}
        mission = normalize_job_to_mission(job)
        remember_mission_state(mission)
        return {
            "status": "success",
            "intent": intent,
            "job_id": job["job_id"],
            "job": job,
            "mission": mission,
            "reply_hint": f"Test Operator job {job['job_id']} is {job['phase']}. Current target is {job['spec']['target_agent']}.",
        }

    if intent == "test_session_report":
        from tools.sloane_jobs import list_jobs, load_job

        job_id = args.get("job_id")
        job = load_job(job_id) if job_id else (list_jobs(limit=1)[0] if list_jobs(limit=1) else None)
        if not job:
            return {"status": "not_found", "intent": intent, "reply_hint": "No completed Sloane test operator report is available yet."}
        mission = normalize_job_to_mission(job)
        remember_mission_state(mission)
        report_path = job.get("artifacts", {}).get("report_text")
        if report_path:
            mission["artifacts"]["report_text"] = report_path
        return {
            "status": "success",
            "intent": intent,
            "job_id": job.get("job_id"),
            "job": job,
            "mission": mission,
            "reply_hint": "That mission does not have a saved report yet." if not report_path else None,
        }

    if intent == "test_session_email":
        from tools.sloane_jobs import approve_job_email

        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "intent": intent, "reply_hint": "I need a job id before I can approve that outbound report."}
        try:
            job = approve_job_email(job_id)
        except FileNotFoundError:
            return {"status": "not_found", "intent": intent, "reply_hint": f"I could not find a Sloane job with id {job_id}."}
        mission = normalize_job_to_mission(job)
        remember_mission_state(mission)
        return {
            "status": "success",
            "intent": intent,
            "job_id": job_id,
            "job": job,
            "mission": mission,
            "reply_hint": f"Understood. Job {job_id} email action is now {job.get('results', {}).get('email', {}).get('status', 'unknown')}.",
        }

    return {
        "status": "planned",
        "intent": intent,
        "mission": {
            "mission_id": plan.get("mission_id"),
            "owner_agent": "hermes",
            "requested_by": plan.get("requested_by"),
            "intent": plan.get("intent"),
            "plan_steps": plan.get("plan_steps", []),
            "active_step": plan.get("active_step"),
            "status": "planned",
            "artifacts": {},
            "memory_links": plan.get("memory_links", []),
            "rollback_checkpoint": plan.get("rollback_checkpoint"),
        },
        "reply_hint": None,
    }


def render_operator_reply(plan_or_result: Dict[str, Any], persona: str = "sloane") -> str:
    reply_hint = str(plan_or_result.get("reply_hint") or "").strip()
    if reply_hint:
        return reply_hint
    mission = plan_or_result.get("mission") or {}
    intent = str(plan_or_result.get("intent") or mission.get("intent") or "general_chat")
    persona_name = "Sloane" if str(persona).lower() == "sloane" else str(persona).title()
    if intent == "test_session_report":
        report_path = mission.get("artifacts", {}).get("report_text")
        if report_path:
            return f"{persona_name} has the mission report ready in the vault at {report_path}."
    if mission.get("job_id"):
        return f"{persona_name} has delegated this mission to Hermes. Job {mission['job_id']} is {mission.get('status', 'active')}."
    return f"{persona_name} has a Hermes plan ready for the next step."


def record_operational_lesson(result: Dict[str, Any], evidence: Optional[List[str]] = None) -> Optional[str]:
    mission = result.get("mission") or {}
    lesson = record_lesson(
        source="ops",
        title=f"Hermes operator lesson: {mission.get('intent', result.get('intent', 'unknown'))}",
        summary=render_operator_reply(result, persona="hermes"),
        tags=["hermes_operator", str(mission.get("intent") or result.get("intent") or "unknown")],
        confidence=0.61,
        evidence_paths=evidence or mission.get("memory_links", []),
        dedupe_key=f"hermes_operator::{mission.get('mission_id') or result.get('job_id') or result.get('intent')}",
    )
    if lesson.get("trusted_artifacts"):
        return lesson.get("dedupe_key")
    return None


def get_operator_snapshot(limit: int = 5) -> Dict[str, Any]:
    from tools.sloane_jobs import list_jobs

    jobs = list_jobs(limit=limit)
    missions = [normalize_job_to_mission(job) for job in jobs]
    return {
        "owner": "hermes",
        "persona_default": "sloane",
        "recent_missions": missions,
        "memory": get_hermes_memory_snapshot(),
        "generated_at": _now(),
    }


def build_operator_grounding(request: str, plan: Optional[Dict[str, Any]] = None) -> str:
    plan = plan or {}
    lines = []
    if plan:
        lines.append("[HERMES PLAN]")
        lines.append(f"- intent: {plan.get('intent', 'general_chat')}")
        lines.append(f"- requested_by: {plan.get('requested_by', 'Rob')}")
        if plan.get("plan_steps"):
            lines.append(
                "- next steps: " + ", ".join(step.get("label", step.get("key", "step")) for step in plan.get("plan_steps", [])[:4])
            )
    ops_brief = build_operational_memory_brief(request)
    blocks = ["\n".join(lines).strip(), ops_brief]
    return "\n\n".join(block for block in blocks if block.strip()).strip()
