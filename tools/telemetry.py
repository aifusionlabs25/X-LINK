import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
TELEMETRY_DIR = ROOT_DIR / "vault" / "telemetry"
LLM_CALLS_PATH = TELEMETRY_DIR / "llm_calls.jsonl"
WORKFLOW_RUNS_PATH = TELEMETRY_DIR / "workflow_runs.jsonl"
GPU_SAMPLES_PATH = TELEMETRY_DIR / "gpu_samples.jsonl"

REFERENCE_CLOUD_PRICING = {
    "openai_gpt_4o": {"input_per_1m": 5.00, "output_per_1m": 15.00},
    "anthropic_sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "gemini_2_5_pro": {"input_per_1m": 3.50, "output_per_1m": 10.50},
}


def ensure_telemetry_dir() -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    ensure_telemetry_dir()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None and limit >= 0:
        return rows[-limit:]
    return rows


def estimate_tokens_from_text(text: str) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    return max(1, math.ceil(len(cleaned) / 4))


def estimate_tokens_from_messages(messages: Iterable[Dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += estimate_tokens_from_text(str(message.get("content") or ""))
        total += 4
    return total


def estimate_cloud_costs(input_tokens: int, output_tokens: int) -> Dict[str, Dict[str, float]]:
    estimates: Dict[str, Dict[str, float]] = {}
    for provider, pricing in REFERENCE_CLOUD_PRICING.items():
        input_cost = (input_tokens / 1_000_000.0) * pricing["input_per_1m"]
        output_cost = (output_tokens / 1_000_000.0) * pricing["output_per_1m"]
        estimates[provider] = {
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(input_cost + output_cost, 6),
        }
    return estimates


def record_llm_call(
    *,
    workflow: str,
    provider: str,
    model: str,
    started_at: datetime,
    ended_at: datetime,
    input_tokens_est: int,
    output_tokens_est: int,
    success: bool,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "timestamp": ended_at.isoformat(),
        "workflow": workflow,
        "provider": provider,
        "model": model,
        "success": success,
        "duration_seconds": round((ended_at - started_at).total_seconds(), 3),
        "input_tokens_est": input_tokens_est,
        "output_tokens_est": output_tokens_est,
        "total_tokens_est": input_tokens_est + output_tokens_est,
        "cloud_cost_estimates": estimate_cloud_costs(input_tokens_est, output_tokens_est),
        "metadata": metadata or {},
    }
    _append_jsonl(LLM_CALLS_PATH, payload)
    return payload


def record_workflow_run(
    *,
    workflow: str,
    run_id: str,
    status: str,
    started_at: datetime,
    ended_at: datetime,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "timestamp": ended_at.isoformat(),
        "workflow": workflow,
        "run_id": run_id,
        "status": status,
        "duration_seconds": round((ended_at - started_at).total_seconds(), 3),
        "metadata": metadata or {},
    }
    _append_jsonl(WORKFLOW_RUNS_PATH, payload)
    return payload


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def capture_gpu_sample(*, workflow: str, run_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,utilization.memory,memory.total,memory.used,power.draw,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(command, encoding="utf-8", timeout=5).strip()
    except Exception as exc:
        _append_jsonl(
            GPU_SAMPLES_PATH,
            {
                "timestamp": datetime.now().isoformat(),
                "workflow": workflow,
                "run_id": run_id,
                "error": str(exc),
                "metadata": metadata or {},
            },
        )
        return None

    if not output:
        return None

    parts = [part.strip() for part in output.splitlines()[0].split(",")]
    if len(parts) < 7:
        return None

    payload = {
        "timestamp": datetime.now().isoformat(),
        "workflow": workflow,
        "run_id": run_id,
        "gpu_name": parts[0],
        "gpu_util_percent": _safe_float(parts[1]),
        "memory_util_percent": _safe_float(parts[2]),
        "memory_total_mb": _safe_float(parts[3]),
        "memory_used_mb": _safe_float(parts[4]),
        "power_draw_watts": _safe_float(parts[5]),
        "temperature_c": _safe_float(parts[6]),
        "metadata": metadata or {},
    }
    _append_jsonl(GPU_SAMPLES_PATH, payload)
    return payload


def get_telemetry_summary(limit: int = 200) -> Dict[str, Any]:
    llm_rows = _read_jsonl(LLM_CALLS_PATH, limit=limit)
    workflow_rows = _read_jsonl(WORKFLOW_RUNS_PATH, limit=limit)
    gpu_rows = _read_jsonl(GPU_SAMPLES_PATH, limit=limit)

    total_cloud_costs: Dict[str, float] = defaultdict(float)
    llm_by_model: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "duration_seconds": 0.0,
            "input_tokens_est": 0,
            "output_tokens_est": 0,
            "estimated_cloud_cost_usd": defaultdict(float),
        }
    )
    llm_by_workflow: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"calls": 0, "duration_seconds": 0.0})

    total_calls = 0
    total_duration = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    for row in llm_rows:
        total_calls += 1
        total_duration += float(row.get("duration_seconds") or 0.0)
        total_input_tokens += int(row.get("input_tokens_est") or 0)
        total_output_tokens += int(row.get("output_tokens_est") or 0)

        model_key = f"{row.get('provider', 'unknown')}::{row.get('model', 'unknown')}"
        workflow_key = str(row.get("workflow") or "unknown")
        model_entry = llm_by_model[model_key]
        model_entry["calls"] += 1
        model_entry["successes"] += 1 if row.get("success") else 0
        model_entry["duration_seconds"] += float(row.get("duration_seconds") or 0.0)
        model_entry["input_tokens_est"] += int(row.get("input_tokens_est") or 0)
        model_entry["output_tokens_est"] += int(row.get("output_tokens_est") or 0)
        llm_by_workflow[workflow_key]["calls"] += 1
        llm_by_workflow[workflow_key]["duration_seconds"] += float(row.get("duration_seconds") or 0.0)

        for provider_name, estimate in (row.get("cloud_cost_estimates") or {}).items():
            cost = float((estimate or {}).get("total_cost_usd") or 0.0)
            total_cloud_costs[provider_name] += cost
            model_entry["estimated_cloud_cost_usd"][provider_name] += cost

    workflow_totals: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"runs": 0, "completed": 0, "errors": 0, "blocked": 0, "duration_seconds": 0.0})
    for row in workflow_rows:
        workflow_key = str(row.get("workflow") or "unknown")
        workflow_totals[workflow_key]["runs"] += 1
        workflow_totals[workflow_key]["duration_seconds"] += float(row.get("duration_seconds") or 0.0)
        status = str(row.get("status") or "").lower()
        if status in {"complete", "completed", "success", "ship", "conditional", "no_ship", "fail_block_release", "no_data"}:
            workflow_totals[workflow_key]["completed"] += 1
        if status in {"no_ship", "fail_block_release", "no_data"}:
            workflow_totals[workflow_key]["blocked"] += 1
        elif status in {"error", "failed"}:
            workflow_totals[workflow_key]["errors"] += 1

    slowest_runs = sorted(workflow_rows, key=lambda row: float(row.get("duration_seconds") or 0.0), reverse=True)[:5]
    latest_gpu = gpu_rows[-1] if gpu_rows else None
    latest_successful_gpu = next((row for row in reversed(gpu_rows) if "error" not in row), latest_gpu)
    recent_gpu_samples = [row for row in gpu_rows if "error" not in row][-30:]

    return {
        "reference_pricing": REFERENCE_CLOUD_PRICING,
        "coverage": {
            "token_status": "partial",
            "token_note": "Per-call token telemetry is strongest for Sloane runtime, MEL simulation, and reviewer/Troy passes. Some older tools are still untracked.",
            "live_refresh_seconds": 30,
        },
        "llm_calls": {
            "count": total_calls,
            "input_tokens_est": total_input_tokens,
            "output_tokens_est": total_output_tokens,
            "average_duration_seconds": round(total_duration / total_calls, 3) if total_calls else 0.0,
            "estimated_cloud_cost_usd": {key: round(value, 6) for key, value in total_cloud_costs.items()},
            "by_model": {
                key: {
                    "calls": value["calls"],
                    "success_rate": round(value["successes"] / value["calls"], 3) if value["calls"] else 0.0,
                    "average_duration_seconds": round(value["duration_seconds"] / value["calls"], 3) if value["calls"] else 0.0,
                    "input_tokens_est": value["input_tokens_est"],
                    "output_tokens_est": value["output_tokens_est"],
                    "estimated_cloud_cost_usd": {p: round(v, 6) for p, v in value["estimated_cloud_cost_usd"].items()},
                }
                for key, value in llm_by_model.items()
            },
            "by_workflow": {
                key: {
                    "calls": value["calls"],
                    "average_duration_seconds": round(value["duration_seconds"] / value["calls"], 3) if value["calls"] else 0.0,
                }
                for key, value in llm_by_workflow.items()
            },
        },
        "workflows": {
            "by_workflow": {
                key: {
                    "runs": value["runs"],
                    "completed": value["completed"],
                    "errors": value["errors"],
                    "blocked": value["blocked"],
                    "average_duration_seconds": round(value["duration_seconds"] / value["runs"], 3) if value["runs"] else 0.0,
                }
                for key, value in workflow_totals.items()
            },
            "slowest_recent_runs": slowest_runs,
        },
        "gpu": {
            "latest_sample": latest_successful_gpu,
            "latest_raw_sample": latest_gpu,
            "sample_count": len(gpu_rows),
            "recent_samples": recent_gpu_samples,
        },
        "files": {
            "llm_calls": str(LLM_CALLS_PATH),
            "workflow_runs": str(WORKFLOW_RUNS_PATH),
            "gpu_samples": str(GPU_SAMPLES_PATH),
        },
    }
