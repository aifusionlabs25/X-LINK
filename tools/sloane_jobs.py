import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.agent_validation import build_validation_profile, evaluate_release_readiness
VAULT_DIR = ROOT_DIR / "vault"
SLOANE_DIR = VAULT_DIR / "sloane_jobs"
JOBS_DIR = SLOANE_DIR / "jobs"
REPORTS_DIR = SLOANE_DIR / "reports"
MEL_DIR = VAULT_DIR / "mel"
EVALS_DIR = VAULT_DIR / "evals"
CONFIG_DIR = ROOT_DIR / "config"
PYTHON_EXE = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable)

AUTO_SEND_RECIPIENT = "aifusionlabs@gmail.com"
SLOANE_SENDER = "novaaifusionlabs@gmail.com"


def _ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def parse_requested_date(raw: str) -> Optional[date]:
    text = (raw or "").strip()
    if not text:
        return None
    formats = [
        "%m.%d.%y",
        "%m.%d.%Y",
        "%m/%d/%y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _eval_session_path(batch_id: str) -> Path:
    safe = str(batch_id or "").replace("/", "__").replace("\\", "__").replace(":", "_")
    return EVALS_DIR / "sessions" / f"{safe}.json"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        tmp_path.replace(path)
    except PermissionError:
        # Windows can briefly hold the destination or temp file open during rapid writes.
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _email_dispatch_succeeded(dispatch: Dict[str, Any]) -> bool:
    if int(dispatch.get("returncode", 1)) != 0:
        return False
    stdout = str(dispatch.get("stdout", "") or "")
    stderr = str(dispatch.get("stderr", "") or "")
    stdout_lower = stdout.lower()
    stderr_lower = stderr.lower()

    if "gmail sent to" in stdout_lower and "successfully" in stdout_lower:
        hard_fail_markers = (
            "failed to connect",
            "timeout",
            "connection refused",
            "login required",
            "unable to locate",
            "could not send",
        )
        if not any(marker in stderr_lower for marker in hard_fail_markers):
            return True

    combined = f"{stdout_lower} {stderr_lower}"
    failure_markers = (
        "failed to connect",
        "timeout",
        "error -",
    )
    return not any(marker in combined for marker in failure_markers)


def _load_agents() -> List[Dict[str, Any]]:
    agents_path = CONFIG_DIR / "agents.yaml"
    with agents_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("agents", [])


def _resolve_agent_slug(target: str) -> str:
    needle = (target or "").strip().lower()
    if not needle:
        return "dani"
    for agent in _load_agents():
        if needle in {str(agent.get("slug", "")).lower(), str(agent.get("name", "")).lower()}:
            return agent.get("slug", needle)
    return needle


def _resolve_default_pack(agent_slug: str) -> str:
    scenarios_dir = CONFIG_DIR / "eval_scenarios"
    preferred = scenarios_dir / f"{agent_slug}_platform_sales.yaml"
    if preferred.exists():
        return preferred.stem
    for path in sorted(scenarios_dir.glob(f"{agent_slug}*.yaml")):
        if path.name != "template.yaml":
            return path.stem
    packs = [p.stem for p in sorted(scenarios_dir.glob("*.yaml")) if p.name != "template.yaml"]
    return packs[0] if packs else "default_pack"


def _socket_open(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False


def _default_steps() -> Dict[str, Dict[str, Any]]:
    return {
        "preflight": {"status": "pending"},
        "sh_lab": {"status": "pending"},
        "xagent_eval": {"status": "pending"},
        "report": {"status": "pending"},
        "email": {"status": "pending"},
    }


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _infer_execution_scope(mission_request: str, params: Dict[str, Any]) -> tuple[bool, bool]:
    if "run_sh_lab" in params or "run_xagent_eval" in params:
        return (
            _normalize_bool(params.get("run_sh_lab"), True),
            _normalize_bool(params.get("run_xagent_eval"), True),
        )

    text = (mission_request or "").strip().lower()

    mentions_sh_lab = any(token in text for token in ("sh lab", "superhero lab", "super hero lab"))
    mentions_eval = any(
        token in text for token in ("x agent eval", "x-agent eval", "xagent eval", "eval only", "run eval")
    )

    sh_lab_only = any(token in text for token in ("sh lab only", "superhero lab only", "super hero lab only"))
    eval_only = any(token in text for token in ("x agent eval only", "x-agent eval only", "xagent eval only"))

    disables_eval = any(
        token in text
        for token in (
            "do not run x agent eval",
            "don't run x agent eval",
            "without x agent eval",
            "no x agent eval",
            "skip x agent eval",
            "sh lab then send",
        )
    )
    disables_sh_lab = any(
        token in text
        for token in (
            "do not run sh lab",
            "don't run sh lab",
            "without sh lab",
            "no sh lab",
            "skip sh lab",
        )
    )

    if sh_lab_only or (mentions_sh_lab and not mentions_eval) or disables_eval:
        return True, False
    if eval_only or (mentions_eval and not mentions_sh_lab) or disables_sh_lab:
        return False, True
    return True, True


def _build_job_spec(mission_request: str, params: Dict[str, Any], *, job_id: Optional[str] = None) -> Dict[str, Any]:
    target_agent = _resolve_agent_slug(params.get("target_agent") or params.get("agent") or "dani")
    scenario_pack = params.get("scenario_pack") or params.get("pack") or _resolve_default_pack(target_agent)
    recipient = (params.get("recipient") or AUTO_SEND_RECIPIENT).strip().lower()
    run_sh_lab, run_xagent_eval = _infer_execution_scope(mission_request, params)
    eval_batch_id = params.get("batch_id") or (f"{job_id}/eval" if job_id else None)

    mel_spec = {
        "agent": target_agent,
        "scenario_pack": scenario_pack,
        "scenarios": int(params.get("mel_scenarios", 3)),
        "max_turns": int(params.get("mel_max_turns", 15)),
        "difficulty": params.get("difficulty", "mixed"),
        "engine": params.get("mel_engine", "v1"),
    }
    eval_spec = {
        "agent": target_agent,
        "batch_id": eval_batch_id,
        "pack": scenario_pack,
        "environment": params.get("environment", "local"),
        "difficulty": params.get("difficulty", "mixed"),
        "runs": int(params.get("eval_runs", 3)),
        "turn_profile": params.get("turn_profile", "standard"),
        "review_mode": params.get("review_mode", "full"),
        "browser_mode": _normalize_bool(params.get("browser_mode"), True),
        "scoring_rubric": params.get("scoring_rubric", "default_v1"),
    }
    auto_send = recipient == AUTO_SEND_RECIPIENT
    validation_profile = build_validation_profile(
        target_agent,
        mission_request=mission_request,
        mode=str(params.get("validation_mode") or "standard"),
    )
    return {
        "mission_request": mission_request,
        "target_agent": target_agent,
        "recipient": recipient,
        "run_sh_lab": run_sh_lab,
        "run_xagent_eval": run_xagent_eval,
        "mel": mel_spec,
        "eval": eval_spec,
        "email_policy": {
            "sender": SLOANE_SENDER,
            "recipient": recipient,
            "auto_send": auto_send,
            "requires_approval": not auto_send,
        },
        "validation_profile": validation_profile,
    }


def create_test_operator_job(mission_request: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _ensure_dirs()
    params = params or {}
    job_id = f"sloane_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    spec = _build_job_spec(mission_request, params, job_id=job_id)
    job = {
        "job_id": job_id,
        "job_type": "test_operator_v1",
        "phase": "queued",
        "status": "queued",
        "created_at": _now(),
        "updated_at": _now(),
        "mission_request": mission_request,
        "spec": spec,
        "steps": _default_steps(),
        "artifacts": {
            "sh_lab_pending": None,
            "sh_lab_batch_summary": None,
            "xagent_eval_batch_summary": None,
            "report_json": None,
            "report_text": None,
        },
        "runtime": {
            "worker_pid": None,
            "mel_pid": None,
            "eval_pid": None,
            "mel_started_at": None,
            "eval_started_at": None,
        },
        "results": {
            "sh_lab": None,
            "xagent_eval": None,
            "summary": None,
            "email": None,
            "release_readiness": None,
        },
        "errors": [],
    }
    _write_json(_job_path(job_id), job)
    return job


def load_job(job_id: str) -> Dict[str, Any]:
    return _read_json(_job_path(job_id))


def save_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job["updated_at"] = _now()
    _write_json(_job_path(job["job_id"]), job)
    return job


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    _ensure_dirs()
    jobs = []
    for path in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        jobs.append(_read_json(path))
    return jobs


def find_jobs_for_date(target_date: date, limit: int = 200) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for job in list_jobs(limit=limit):
        created_at = _parse_iso(job.get("created_at"))
        if created_at and created_at.date() == target_date:
            matches.append(job)
    return matches


def build_test_session_digest(target_date: date, recipient: str) -> Dict[str, Any]:
    jobs = find_jobs_for_date(target_date)
    date_label = target_date.strftime("%B %d, %Y")
    subject = f"Sloane Test Session Digest | {date_label}"
    if not jobs:
        body = (
            f"Rob,\n\n"
            f"I couldn't find any Sloane test sessions recorded for {date_label}.\n\n"
            f"Sloane"
        )
        return {"subject": subject, "body": body, "count": 0, "jobs": []}

    completed_jobs = [job for job in jobs if str(job.get("phase")) == "completed"]
    recommendations: Dict[str, int] = {}
    for job in jobs:
        recommendation = (
            job.get("results", {}).get("release_readiness") or {}
        ).get("recommendation")
        if recommendation:
            recommendations[recommendation] = recommendations.get(recommendation, 0) + 1

    quick_read_parts = []
    if completed_jobs:
        quick_read_parts.append(f"{len(completed_jobs)} completed")
    if recommendations:
        ordered = ", ".join(f"{count} {label}" for label, count in sorted(recommendations.items()))
        quick_read_parts.append(ordered)
    quick_read = "; ".join(quick_read_parts) if quick_read_parts else "mostly in-flight work with limited completed artifacts"

    lines = [
        "Rob,",
        "",
        f"Here is the test-session digest for {date_label}.",
        "",
        f"Total sessions: {len(jobs)}",
        f"My quick read: {quick_read}.",
        "",
        "Session details:",
        "",
    ]
    for job in jobs:
        agent = str(job.get("spec", {}).get("target_agent") or "unknown").title()
        created_at = _parse_iso(job.get("created_at"))
        created_label = created_at.strftime("%I:%M %p").lstrip("0") if created_at else "Unknown time"
        phase = str(job.get("phase") or "unknown").replace("_", " ")
        sh_lab = job.get("results", {}).get("sh_lab") or {}
        baseline = sh_lab.get("baseline", {}) or {}
        score = baseline.get("score")
        release_readiness = job.get("results", {}).get("release_readiness") or {}
        recommendation = release_readiness.get("recommendation")
        top_failures = release_readiness.get("top_failure_categories") or []
        mission = str(job.get("mission_request") or "").strip()
        scope_bits = []
        spec = job.get("spec") or {}
        if spec.get("run_sh_lab"):
            scope_bits.append("SH Lab")
        if spec.get("run_xagent_eval"):
            scope_bits.append("X Agent Eval")
        scope = " + ".join(scope_bits) if scope_bits else "Mission run"
        lines.append(f"{created_label} | {agent} | {scope}")
        lines.append(f"Job: {job.get('job_id')}")
        lines.append(f"Status: {phase}")
        if score is not None:
            lines.append(f"Primary score: SH Lab {score}")
        if recommendation:
            lines.append(f"Release recommendation: {recommendation}")
        if top_failures:
            lines.append(f"Main issue: {', '.join(top_failures[:3])}")
        if mission:
            lines.append(f"Summary: {mission}")
        lines.append("")
    lines.extend([
        "If you'd like, I can follow this with a tighter recommendation memo instead of the full session-by-session view.",
        "",
        "Sloane",
    ])
    return {"subject": subject, "body": "\n".join(lines), "count": len(jobs), "jobs": jobs}


def _set_step(job: Dict[str, Any], key: str, status: str, **extra: Any) -> None:
    step = job["steps"].setdefault(key, {})
    step["status"] = status
    step["updated_at"] = _now()
    step.update(extra)


def _mark_failed(job: Dict[str, Any], reason: str) -> Dict[str, Any]:
    job["phase"] = "failed"
    job["status"] = "failed"
    job["errors"].append({"timestamp": _now(), "message": reason})
    return save_job(job)


def _latest_matching_json(directory: Path, suffix: str = ".json", after_iso: Optional[str] = None, contains: Optional[str] = None) -> Optional[Path]:
    if not directory.exists():
        return None
    after_dt = datetime.fromisoformat(after_iso) if after_iso else None
    candidates: List[Path] = []
    for path in directory.glob(f"*{suffix}"):
        if contains and contains not in path.name:
            continue
        if after_dt and datetime.fromtimestamp(path.stat().st_mtime) < after_dt:
            continue
        candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _collect_mel_artifacts(job: Dict[str, Any]) -> Dict[str, Any]:
    started_at = job["runtime"].get("mel_started_at")
    pending_path = _latest_matching_json(MEL_DIR / "pending", after_iso=started_at, contains=job["spec"]["target_agent"])
    result: Dict[str, Any] = {}
    if pending_path:
        pending = _read_json(pending_path)
        result["pending_id"] = pending.get("pending_id")
        result["path"] = str(pending_path)
        result["score"] = pending.get("recommendation", {}).get("score") or pending.get("baseline", {}).get("score")
        result["baseline"] = pending.get("baseline")
        result["recommendation"] = pending.get("recommendation")
        recommended_batch = pending.get("recommendation", {}).get("batch_id")
        baseline_batch = pending.get("baseline", {}).get("batch_id")
        batch_id = recommended_batch or baseline_batch
        if batch_id:
            batch_path = EVALS_DIR / "batches" / batch_id / "batch_summary.json"
            if batch_path.exists():
                result["batch_summary_path"] = str(batch_path)
    return result


def _collect_eval_artifacts(job: Dict[str, Any]) -> Dict[str, Any]:
    batch_id = job.get("spec", {}).get("eval", {}).get("batch_id")
    session_path = _eval_session_path(batch_id) if batch_id else (EVALS_DIR / "active_session.json")
    session = _read_json(session_path, {})
    batch_id = session.get("batch_id")
    result: Dict[str, Any] = {"batch_id": batch_id}
    if batch_id:
        batch_path = EVALS_DIR / "batches" / batch_id / "batch_summary.json"
        if batch_path.exists():
            summary = _read_json(batch_path)
            result["summary"] = summary
            result["path"] = str(batch_path)
    return result


def _summarize_batch(summary: Dict[str, Any], label: str) -> Dict[str, Any]:
    if not summary:
        return {"label": label, "status": "not_found"}
    top_failures = summary.get("top_failure_categories") or []
    return {
        "label": label,
        "batch_id": summary.get("batch_id"),
        "average_score": summary.get("average_score"),
        "pass_rate": summary.get("pass_rate"),
        "verdict": summary.get("verdict"),
        "top_failure_categories": top_failures[:3],
        "harness_artifacts": [
            artifact
            for run in summary.get("runs", [])
            for artifact in run.get("harness_artifacts", [])
        ][:5],
    }


def _format_duration(started_at: Optional[str], ended_at: Optional[str]) -> str:
    start_dt = _parse_iso(started_at)
    end_dt = _parse_iso(ended_at)
    if not start_dt or not end_dt:
        return "Unknown"
    total_seconds = max(0, int((end_dt - start_dt).total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _compose_report(job: Dict[str, Any]) -> Dict[str, str]:
    sh_lab = job["results"].get("sh_lab") or {}
    x_eval = job["results"].get("xagent_eval") or {}
    sh_lab_summary_raw = _read_json(Path(sh_lab["batch_summary_path"])) if sh_lab.get("batch_summary_path") else {}
    sh_lab_summary = _summarize_batch(sh_lab_summary_raw, "SuperHero Lab")
    x_eval_summary = _summarize_batch(x_eval.get("summary", {}), "X Agent Eval")
    release_readiness = evaluate_release_readiness(
        job["spec"].get("validation_profile", {}),
        sh_lab_summary=sh_lab_summary_raw,
        xagent_eval_summary=x_eval.get("summary", {}),
    )
    job["results"]["release_readiness"] = release_readiness

    headline_parts = []
    if sh_lab_summary.get("average_score") is not None:
        headline_parts.append(f"SH Lab {sh_lab_summary['average_score']}")
    if x_eval_summary.get("average_score") is not None:
        headline_parts.append(f"Eval {x_eval_summary['average_score']}")
    headline = " | ".join(headline_parts) if headline_parts else "Run completed with partial artifacts"
    duration_text = _format_duration(job.get("created_at"), job.get("updated_at"))
    generated_at = job.get("updated_at")
    target_agent = job["spec"]["target_agent"]
    recommendation = release_readiness.get('recommendation', 'unknown')
    top_failures = ", ".join(release_readiness.get("top_failure_categories") or ["none noted"])
    troy_note = sh_lab.get("recommendation", {}).get("rationale")
    troy_patch = sh_lab.get("recommendation", {}).get("patch")

    lines = [
        f"Sloane Test Operator Report",
        f"Job ID: {job['job_id']}",
        f"Generated: {generated_at}",
        f"Target Agent: {target_agent}",
        f"Mission: {job['mission_request']}",
        f"Validation Family: {job['spec'].get('validation_profile', {}).get('family_label', 'Unknown')}",
        f"Duration: {duration_text}",
        "",
        f"Summary: {headline}",
        f"Release Recommendation: {recommendation}",
        "",
        "Key Findings:",
    ]
    for summary in (sh_lab_summary, x_eval_summary):
        if summary.get("status") == "not_found":
            continue
        lines.append(f"- {summary['label']}: score {summary.get('average_score')} | pass rate {summary.get('pass_rate')} | verdict {summary.get('verdict')}")
        if summary.get("top_failure_categories"):
            lines.append(f"- {summary['label']} top failures: {', '.join(summary['top_failure_categories'])}")
        if summary.get("harness_artifacts"):
            lines.append(f"- {summary['label']} harness artifacts: {', '.join(summary['harness_artifacts'])}")
    lines.extend([
        "",
        "Release Gates:",
    ])
    for gate in release_readiness.get("gates", []):
        lines.append(f"- {gate['label']}: {gate['status']} | {gate['detail']}")
    lines.extend([
        "",
        "Artifacts:",
        f"- SH Lab pending: {job['artifacts'].get('sh_lab_pending') or 'Not found'}",
        f"- SH Lab batch summary: {job['artifacts'].get('sh_lab_batch_summary') or 'Not found'}",
        f"- X Agent Eval batch summary: {job['artifacts'].get('xagent_eval_batch_summary') or 'Not found'}",
    ])
    report_body = "\n".join(lines)

    email_lines = [
        f"Rob,",
        "",
        f"I've finished the latest {target_agent.title()} test run.",
        f"My short read is {recommendation}: the run came back at {headline.lower()}, and the main issue still appears to be {top_failures}.",
        "",
        "What stands out:",
    ]
    if sh_lab_summary.get("average_score") is not None:
        email_lines.append(
            f"- SuperHero Lab landed at {sh_lab_summary.get('average_score')} with a {sh_lab_summary.get('verdict')} verdict."
        )
    if x_eval_summary.get("status") != "not_found" and x_eval_summary.get("average_score") is not None:
        email_lines.append(
            f"- X-Agent Eval landed at {x_eval_summary.get('average_score')} with a {x_eval_summary.get('verdict')} verdict."
        )
    if sh_lab_summary.get("top_failure_categories"):
        email_lines.append(f"- Top SH Lab weakness: {', '.join(sh_lab_summary.get('top_failure_categories')[:3])}.")
    if x_eval_summary.get("status") != "not_found" and x_eval_summary.get("top_failure_categories"):
        email_lines.append(f"- Top Eval weakness: {', '.join(x_eval_summary.get('top_failure_categories')[:3])}.")
    if troy_note:
        email_lines.append(f"- Troy's rationale: {troy_note}")
    if troy_patch:
        email_lines.append(f"- Troy's suggested adjustment: {troy_patch}")

    email_lines.extend([
        "",
        f"My recommendation is to {recommendation.replace('_', ' ')} before broad rollout.",
        f"Run details: {generated_at} | Duration: {duration_text}",
        "",
        "Artifacts are saved in X-LINK if you want the raw detail:",
        f"- SH Lab pending: {job['artifacts'].get('sh_lab_pending') or 'Not found'}",
        f"- SH Lab batch summary: {job['artifacts'].get('sh_lab_batch_summary') or 'Not found'}",
        f"- X Agent Eval batch summary: {job['artifacts'].get('xagent_eval_batch_summary') or 'Not found'}",
        "",
        "If you'd like, I can turn this into a next-step action plan instead of leaving it as a result summary.",
        "",
        "Sloane",
    ])
    email_body = "\n".join(email_lines)
    subject = f"Sloane Test Report | {target_agent} | {headline}"
    return {"subject": subject, "body": report_body, "email_body": email_body}


def _save_report(job: Dict[str, Any], subject: str, body: str) -> Dict[str, Any]:
    report_json_path = REPORTS_DIR / f"{job['job_id']}.json"
    report_text_path = REPORTS_DIR / f"{job['job_id']}.txt"
    payload = {
        "job_id": job["job_id"],
        "subject": subject,
        "body": body,
        "results": job["results"],
        "artifacts": job["artifacts"],
        "generated_at": _now(),
    }
    _write_json(report_json_path, payload)
    with report_text_path.open("w", encoding="utf-8") as fh:
        fh.write(body)
    job["artifacts"]["report_json"] = str(report_json_path)
    job["artifacts"]["report_text"] = str(report_text_path)
    return job


def _dispatch_email(subject: str, body: str, recipient: str, attachments: Optional[List[str]] = None) -> Dict[str, Any]:
    args = [
        str(PYTHON_EXE),
        str(ROOT_DIR / "tools" / "gsuite_handler.py"),
        "--action",
        "gmail_send",
        "--to",
        recipient,
        "--subject",
        subject,
        "--body",
        body,
    ]
    if attachments:
        args.extend(["--attachments", "||".join(str(path) for path in attachments if path)])
    proc = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT_DIR))
    dispatch = {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "sent_at": _now(),
        "attachments": attachments or [],
    }
    dispatch["success"] = _email_dispatch_succeeded(dispatch)
    return dispatch


def approve_job_email(job_id: str) -> Dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise FileNotFoundError(job_id)
    email_payload = job["results"].get("email") or {}
    if not email_payload.get("subject") or not email_payload.get("body") or not email_payload.get("recipient"):
        return job

    # Regenerate the report and email body so resends use the latest Sloane format.
    subject_body = _compose_report(job)
    _save_report(job, subject_body["subject"], subject_body["body"])
    email_payload.update({
        "subject": subject_body["subject"],
        "body": subject_body.get("email_body") or subject_body["body"],
        "report_body": subject_body["body"],
    })

    if job.get("phase") == "waiting_for_approval":
        pass
    elif email_payload.get("status") in {"sent", "failed"}:
        _set_step(job, "email", "running", resend=True)
    else:
        return job

    dispatch = _dispatch_email(email_payload["subject"], email_payload["body"], email_payload["recipient"])
    dispatch_ok = bool(dispatch.get("success")) if "success" in dispatch else _email_dispatch_succeeded(dispatch)
    email_payload.update({"dispatch": dispatch, "status": "sent" if dispatch_ok else "failed"})
    job["results"]["email"] = email_payload
    job["phase"] = "completed" if dispatch_ok else "failed"
    job["status"] = job["phase"]
    _set_step(job, "email", "done" if dispatch_ok else "error", result=dispatch)
    return save_job(job)


def cancel_job(job_id: str) -> Dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise FileNotFoundError(job_id)
    pid = job.get("runtime", {}).get("worker_pid")
    if pid:
        try:
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], shell=True)
        except Exception:
            pass
    job["phase"] = "failed"
    job["status"] = "cancelled"
    _set_step(job, "report", "cancelled")
    return save_job(job)


def start_job(job_id: str) -> Dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise FileNotFoundError(job_id)
    worker_args = [str(PYTHON_EXE), str(ROOT_DIR / "tools" / "sloane_jobs.py"), "--worker", job_id]
    proc = subprocess.Popen(worker_args, cwd=str(ROOT_DIR))
    job["runtime"]["worker_pid"] = proc.pid
    job["phase"] = "planning"
    job["status"] = "running"
    return save_job(job)


def _await_mel(job: Dict[str, Any], timeout_seconds: int = 5400) -> Dict[str, Any]:
    progress_path = MEL_DIR / "progress.json"
    start = time.time()
    last_change = start
    last_snapshot = ""
    started_at = _parse_iso(job.get("runtime", {}).get("mel_started_at"))
    target_agent = job.get("spec", {}).get("target_agent")
    relevant_seen = False
    while time.time() - start < timeout_seconds:
        progress = _read_json(progress_path, {})
        snapshot = json.dumps(progress.get("events", [])[-1:] if progress.get("events") else [])
        if snapshot != last_snapshot:
            last_snapshot = snapshot
            last_change = time.time()
        events = progress.get("events", [])
        latest = events[-1] if events else {}
        latest_ts = _parse_iso(latest.get("timestamp"))
        latest_agent = str(progress.get("agent") or latest.get("agent") or "").strip().lower()
        is_relevant = bool(
            latest
            and latest_agent == str(target_agent or "").strip().lower()
            and (started_at is None or (latest_ts and latest_ts >= started_at))
        )
        if is_relevant:
            relevant_seen = True
        _set_step(job, "sh_lab", "running", progress=latest, running=progress.get("running"))
        save_job(job)
        if relevant_seen and progress and not progress.get("running"):
            return progress
        if time.time() - last_change > 600:
            raise TimeoutError("SuperHero Lab progress stalled for over 10 minutes.")
        time.sleep(5)
    raise TimeoutError("SuperHero Lab did not finish before timeout.")


def _await_eval(job: Dict[str, Any], proc: subprocess.Popen, timeout_seconds: int = 5400) -> Dict[str, Any]:
    batch_id = job.get("spec", {}).get("eval", {}).get("batch_id")
    session_path = _eval_session_path(batch_id) if batch_id else (EVALS_DIR / "active_session.json")
    start = time.time()
    started_at = _parse_iso(job.get("runtime", {}).get("eval_started_at"))
    target_agent = str(job.get("spec", {}).get("target_agent") or "").strip().lower()
    relevant_seen = False
    while time.time() - start < timeout_seconds:
        session = _read_json(session_path, {})
        session_started = _parse_iso(session.get("started_at"))
        session_agent = str(session.get("params", {}).get("agent") or "").strip().lower()
        is_relevant = bool(
            session
            and session_agent == target_agent
            and (started_at is None or (session_started and session_started >= started_at))
        )
        if is_relevant:
            relevant_seen = True
        _set_step(job, "xagent_eval", "running", session=session)
        save_job(job)
        if proc.poll() is not None and relevant_seen:
            return session
        if proc.poll() is not None and not relevant_seen:
            return session
        if relevant_seen and session.get("status") in {"completed", "failed"}:
            return session
        time.sleep(5)
    raise TimeoutError("X Agent Eval did not finish before timeout.")


def run_job_worker(job_id: str) -> Dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise FileNotFoundError(job_id)

    job["phase"] = "planning"
    job["status"] = "running"
    _set_step(job, "preflight", "running")
    save_job(job)

    if not _socket_open(11434):
        return _mark_failed(job, "Ollama is not reachable on port 11434.")
    if job["spec"]["run_xagent_eval"] and job["spec"]["eval"].get("environment") == "local" and not _socket_open(3000):
        return _mark_failed(job, "Local demo server is not reachable on port 3000.")
    _set_step(job, "preflight", "done", checks={"ollama": True, "dojo": _socket_open(3000), "hub": _socket_open(5001)})
    save_job(job)

    try:
        if job["spec"]["run_sh_lab"]:
            job["phase"] = "running"
            _set_step(job, "sh_lab", "running")
            save_job(job)
            mel = job["spec"]["mel"]
            mel_args = [
                str(PYTHON_EXE),
                str(ROOT_DIR / "tools" / ("mel_v2_runner.py" if str(mel.get("engine")).lower() == "v2" else "mel_pilot.py")),
                "--agent",
                mel["agent"],
                "--pack",
                mel["scenario_pack"],
                "--scenarios",
                str(mel["scenarios"]),
                "--turns",
                str(mel["max_turns"]),
            ]
            if mel.get("difficulty") and mel.get("difficulty") != "mixed":
                mel_args.extend(["--difficulty", str(mel["difficulty"])])
            mel_proc = subprocess.Popen(mel_args, cwd=str(ROOT_DIR))
            job["runtime"]["mel_pid"] = mel_proc.pid
            job["runtime"]["mel_started_at"] = _now()
            save_job(job)
            _await_mel(job)
            mel_artifacts = _collect_mel_artifacts(job)
            job["results"]["sh_lab"] = mel_artifacts
            job["artifacts"]["sh_lab_pending"] = mel_artifacts.get("path")
            job["artifacts"]["sh_lab_batch_summary"] = mel_artifacts.get("batch_summary_path")
            _set_step(job, "sh_lab", "done", result=mel_artifacts)
            save_job(job)

        if job["spec"]["run_xagent_eval"]:
            _set_step(job, "xagent_eval", "running")
            save_job(job)
            eval_args = [
                str(PYTHON_EXE),
                str(ROOT_DIR / "tools" / "run_eval.py"),
                json.dumps(job["spec"]["eval"]),
            ]
            eval_proc = subprocess.Popen(eval_args, cwd=str(ROOT_DIR))
            job["runtime"]["eval_pid"] = eval_proc.pid
            job["runtime"]["eval_started_at"] = _now()
            save_job(job)
            _await_eval(job, eval_proc)
            eval_artifacts = _collect_eval_artifacts(job)
            job["results"]["xagent_eval"] = eval_artifacts
            job["artifacts"]["xagent_eval_batch_summary"] = eval_artifacts.get("path")
            _set_step(job, "xagent_eval", "done", result={"batch_id": eval_artifacts.get("batch_id")})
            save_job(job)

        job["phase"] = "reporting"
        _set_step(job, "report", "running")
        subject_body = _compose_report(job)
        job["results"]["summary"] = {
            "headline": subject_body["subject"],
            "generated_at": _now(),
            "validation_family": job["spec"].get("validation_profile", {}).get("family"),
        }
        _save_report(job, subject_body["subject"], subject_body["body"])
        _set_step(job, "report", "done", report_path=job["artifacts"]["report_text"])
        save_job(job)

        email_payload = {
            "sender": SLOANE_SENDER,
            "recipient": job["spec"]["email_policy"]["recipient"],
            "subject": subject_body["subject"],
            "body": subject_body.get("email_body") or subject_body["body"],
            "report_body": subject_body["body"],
            "status": "pending",
            "requires_approval": job["spec"]["email_policy"]["requires_approval"],
        }
        job["results"]["email"] = email_payload

        if job["spec"]["email_policy"]["auto_send"]:
            _set_step(job, "email", "running")
            dispatch = _dispatch_email(email_payload["subject"], email_payload["body"], email_payload["recipient"])
            dispatch_ok = bool(dispatch.get("success")) if "success" in dispatch else _email_dispatch_succeeded(dispatch)
            email_payload.update({"dispatch": dispatch, "status": "sent" if dispatch_ok else "failed"})
            job["phase"] = "completed" if dispatch_ok else "failed"
            job["status"] = job["phase"]
            _set_step(job, "email", "done" if dispatch_ok else "error", result=dispatch)
        else:
            job["phase"] = "waiting_for_approval"
            job["status"] = "waiting_for_approval"
            _set_step(job, "email", "waiting_for_approval", recipient=email_payload["recipient"])

        return save_job(job)
    except Exception as exc:
        return _mark_failed(job, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sloane job worker")
    parser.add_argument("--worker", help="Run the background worker for a job id")
    args = parser.parse_args()
    if args.worker:
        run_job_worker(args.worker)


if __name__ == "__main__":
    main()
