"""
Overnight MEL loop runner.

Runs repeated MEL cycles for a target agent, auto-approves only strong
improvements, rejects weak candidates, and writes a morning summary.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.mel_pilot import apply_approval, reject_approval, run_evolution
from tools.telemetry import capture_gpu_sample, record_workflow_run

OVERNIGHT_DIR = os.path.join(ROOT_DIR, "vault", "mel", "overnight")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_pending(pending_id: str) -> Dict[str, Any]:
    path = os.path.join(ROOT_DIR, "vault", "mel", "pending", f"{pending_id}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def best_result_from_pending(pending: Dict[str, Any]) -> Dict[str, Any]:
    recommendation = pending.get("recommendation", {}) or {}
    return {
        "variant": recommendation.get("variant"),
        "score": float(recommendation.get("score") or 0),
        "improvement": float(recommendation.get("improvement") or 0),
        "passes_threshold": bool(recommendation.get("passes_threshold")),
    }


def category_avg(result: Dict[str, Any], key: str) -> float:
    return float(((result or {}).get("category_averages") or {}).get(key) or 0)


def should_auto_approve(
    pending: Dict[str, Any],
    *,
    min_improvement: float = 8.0,
    min_score: float = 78.0,
) -> (bool, str):
    baseline = pending.get("baseline", {}) or {}
    recommendation = pending.get("recommendation", {}) or {}
    challengers = pending.get("challengers", []) or []
    winner_variant = recommendation.get("variant")
    winner_entry = next((c for c in challengers if c.get("variant") == winner_variant), None) or {}
    winner_result = winner_entry.get("result", {}) or {}

    baseline_score = float(baseline.get("score") or 0)
    best_score = float(recommendation.get("score") or 0)
    improvement = float(recommendation.get("improvement") or 0)
    baseline_pass_rate = float(baseline.get("pass_rate") or 0)
    best_pass_rate = float(winner_result.get("pass_rate") or 0)

    baseline_accuracy = category_avg(baseline, "accuracy_groundedness")
    best_accuracy = category_avg(winner_result, "accuracy_groundedness")
    baseline_compliance = category_avg(baseline, "compliance_safety")
    best_compliance = category_avg(winner_result, "compliance_safety")
    best_loop = max(
        category_avg(winner_result, "loop_avoidance"),
        category_avg(winner_result, "flow_naturalness"),
    )
    best_progression = max(
        category_avg(winner_result, "conversational_progression"),
        category_avg(winner_result, "task_progression"),
        category_avg(winner_result, "strategic_progression"),
    )
    best_brevity = category_avg(winner_result, "brevity_efficiency")

    if best_score < baseline_score:
        return False, "best score regressed"
    if improvement < min_improvement:
        return False, f"improvement {improvement:.1f} below threshold {min_improvement:.1f}"
    if best_score < min_score:
        return False, f"best score {best_score:.1f} below threshold {min_score:.1f}"
    if best_pass_rate < baseline_pass_rate:
        return False, "pass rate regressed"
    if best_compliance < 5.0 or baseline_compliance < 5.0:
        return False, "compliance is not clean"
    if best_accuracy < max(4.0, baseline_accuracy):
        return False, "groundedness regressed"
    if best_loop < 3.0:
        return False, "loop avoidance still too low"
    if best_progression < 3.0:
        return False, "conversational progression still too low"
    if best_brevity < 2.5:
        return False, "brevity still too weak"
    return True, "strong overnight promotion candidate"


def write_cycle_log(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_summary(path: str, cycles: List[Dict[str, Any]], agent: str) -> None:
    lines = [
        f"# Overnight MEL Summary - {agent}",
        "",
        f"Generated: {datetime.now().isoformat()}",
        "",
    ]
    approved = [c for c in cycles if c["decision"] == "approved"]
    rejected = [c for c in cycles if c["decision"] == "rejected"]
    errors = [c for c in cycles if c["decision"] == "error"]
    lines.extend([
        f"- Total cycles: {len(cycles)}",
        f"- Approved: {len(approved)}",
        f"- Rejected: {len(rejected)}",
        f"- Errors: {len(errors)}",
        "",
        "## Cycle Results",
        "",
    ])
    for cycle in cycles:
        lines.extend([
            f"### Cycle {cycle['cycle']}",
            f"- Pack: {cycle['pack']}",
            f"- Pending ID: {cycle.get('pending_id', 'n/a')}",
            f"- Baseline: {cycle.get('baseline_score', 0)}",
            f"- Best: {cycle.get('best_score', 0)}",
            f"- Improvement: {cycle.get('improvement', 0)}",
            f"- Decision: {cycle['decision']}",
            f"- Reason: {cycle['reason']}",
            "",
        ])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")


async def run_overnight_loop(
    *,
    agent: str,
    packs: List[str],
    cycles: int,
    scenarios: int,
    turns: int,
    difficulty: str,
    min_improvement: float,
    min_score: float,
) -> Dict[str, Any]:
    ensure_dir(OVERNIGHT_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"overnight_{agent}_{ts}"
    run_dir = os.path.join(OVERNIGHT_DIR, run_id)
    ensure_dir(run_dir)
    cycle_log_path = os.path.join(run_dir, "cycles.jsonl")
    summary_path = os.path.join(run_dir, "summary.md")

    started_at = datetime.now()
    results: List[Dict[str, Any]] = []
    capture_gpu_sample(workflow="overnight_mel_loop", run_id=run_id, metadata={"agent": agent, "phase": "start"})

    for idx in range(cycles):
        pack = packs[idx % len(packs)]
        cycle_no = idx + 1
        try:
            outcome = await run_evolution(
                agent_slug=agent,
                scenario_pack=pack,
                num_scenarios=scenarios,
                max_turns=turns,
                difficulty=difficulty,
            )
            pending_id = outcome.get("pending_id")
            if not pending_id:
                payload = {
                    "cycle": cycle_no,
                    "pack": pack,
                    "decision": "error",
                    "reason": outcome.get("error", "missing pending id"),
                }
                results.append(payload)
                write_cycle_log(cycle_log_path, payload)
                continue

            pending = load_pending(pending_id)
            baseline_score = float((pending.get("baseline") or {}).get("score") or 0)
            best = best_result_from_pending(pending)
            approved, reason = should_auto_approve(
                pending,
                min_improvement=min_improvement,
                min_score=min_score,
            )
            if approved:
                apply_approval(pending_id)
                decision = "approved"
            else:
                reject_approval(pending_id)
                decision = "rejected"
            payload = {
                "cycle": cycle_no,
                "pack": pack,
                "pending_id": pending_id,
                "baseline_score": baseline_score,
                "best_score": best["score"],
                "improvement": best["improvement"],
                "variant": best["variant"],
                "decision": decision,
                "reason": reason,
            }
            results.append(payload)
            write_cycle_log(cycle_log_path, payload)
        except Exception as exc:
            payload = {
                "cycle": cycle_no,
                "pack": pack,
                "decision": "error",
                "reason": str(exc),
            }
            results.append(payload)
            write_cycle_log(cycle_log_path, payload)

    write_summary(summary_path, results, agent)
    ended_at = datetime.now()
    record_workflow_run(
        workflow="overnight_mel_loop",
        run_id=run_id,
        status="complete",
        started_at=started_at,
        ended_at=ended_at,
        metadata={
            "agent": agent,
            "cycles": cycles,
            "packs": packs,
            "approved": len([r for r in results if r["decision"] == "approved"]),
            "rejected": len([r for r in results if r["decision"] == "rejected"]),
            "errors": len([r for r in results if r["decision"] == "error"]),
            "summary_path": summary_path,
        },
    )
    capture_gpu_sample(workflow="overnight_mel_loop", run_id=run_id, metadata={"agent": agent, "phase": "complete"})
    return {
        "status": "complete",
        "run_id": run_id,
        "run_dir": run_dir,
        "summary_path": summary_path,
        "cycle_log_path": cycle_log_path,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated MEL cycles overnight with guarded auto-approval.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--packs", default="")
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--scenarios", type=int, default=3)
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--difficulty", default="mixed")
    parser.add_argument("--min-improvement", type=float, default=8.0)
    parser.add_argument("--min-score", type=float, default=78.0)
    args = parser.parse_args()

    packs = [p.strip() for p in args.packs.split(",") if p.strip()] or ["default_pack"]
    result = asyncio.run(
        run_overnight_loop(
            agent=args.agent,
            packs=packs,
            cycles=args.cycles,
            scenarios=args.scenarios,
            turns=args.turns,
            difficulty=args.difficulty,
            min_improvement=args.min_improvement,
            min_score=args.min_score,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
