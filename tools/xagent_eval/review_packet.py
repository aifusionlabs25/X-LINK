"""
X-Agent Eval v1 — Review Packet Generator
Produces Troy-ready review output for persona refinement.
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import BatchSummary, Scorecard

logger = logging.getLogger("xagent_eval.review_packet")

VAULT_DIR = os.path.join(ROOT_DIR, "vault")


def generate_review_packet(
    batch_summary: BatchSummary,
    scorecards: List[Scorecard],
    scenarios: List[dict],
) -> str:
    """Generate a Troy-ready review packet as formatted text."""

    lines = []
    lines.append("=" * 70)
    lines.append("X-AGENT EVAL — REVIEW PACKET")
    lines.append("=" * 70)
    lines.append(f"Generated:      {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Target Agent:   {batch_summary.target_agent}")
    lines.append(f"Environment:    {batch_summary.environment}")
    lines.append(f"Scenario Pack:  {batch_summary.scenario_pack}")
    lines.append(f"Batch ID:       {batch_summary.batch_id}")
    lines.append("")

    # ── Run Summary ──────────────────────────────────────────
    lines.append("-" * 70)
    lines.append("RUN SUMMARY")
    lines.append("-" * 70)
    lines.append(f"Total Runs:     {batch_summary.total_runs}")
    lines.append(f"Passed:         {batch_summary.passed}")
    lines.append(f"Failed:         {batch_summary.failed}")
    lines.append(f"Pass Rate:      {batch_summary.pass_rate}%")
    lines.append(f"Average Score:  {batch_summary.average_score}/100")
    lines.append(f"Verdict:        {batch_summary.verdict}")
    lines.append("")

    # ── Category Averages ────────────────────────────────────
    lines.append("-" * 70)
    lines.append("SCORE BY CATEGORY (average across all runs)")
    lines.append("-" * 70)
    for cat_key, avg in sorted(batch_summary.category_averages.items(),
                                key=lambda x: x[1]):
        bar = "█" * int(avg) + "░" * (5 - int(avg))
        flag = " ⚠" if avg < 3.0 else ""
        lines.append(f"  {cat_key:<30} {avg:.1f}/5.0  {bar}{flag}")
    lines.append("")

    # ── Failed Runs / Infrastructure Errors ──────────────────
    all_meta = batch_summary.data.get("all_metadata", [])
    failed_runs = [s for s in scorecards if s.pass_fail in ("FAIL", "FAIL_BLOCK_RELEASE")]
    
    # Identify runs with errors but no scorecard
    meta_errors = [m for m in all_meta if m.get("status") == "error" or m.get("classification") in ("transport_session_failure", "scenario_mismatch", "review_runtime_failure")]
    
    if failed_runs or meta_errors:
        lines.append("-" * 70)
        lines.append("FAILURE RECAP & ERROR LOG")
        lines.append("-" * 70)
        
        # List metadata errors first (Infrastructure/Gating)
        for m in meta_errors:
            lines.append(f"  Run {m.get('run_id')}:")
            lines.append(f"    Scenario:   {m.get('scenario_title')}")
            lines.append(f"    Classification: {m.get('classification', 'unknown')}")
            lines.append(f"    Error:      {m.get('error_code', 'N/A')}")
            lines.append(f"    Message:    {m.get('error_message', 'No details.')}")
            lines.append("")

        # List scored failures
        for sc in failed_runs:
            scenario = next((s for s in scenarios if s.get("scenario_id") == sc.scenario_id), {})
            lines.append(f"  Run {sc.run_id}:")
            lines.append(f"    Scenario:  {scenario.get('title', sc.scenario_id)}")
            lines.append(f"    Score:     {sc.overall_score}/100")
            lines.append(f"    Verdict:   {sc.pass_fail}")
            if sc.critical_failures:
                for cf in sc.critical_failures:
                    lines.append(f"    🚨 CRITICAL: {cf}")
            lines.append("")
    elif not scorecards:
        lines.append("-" * 70)
        lines.append("FAILURE RECAP")
        lines.append("-" * 70)
        lines.append("  No scorecards generated. Entire batch failed or was blocked.\n")
    else:
        lines.append("No failed runs detected.\n")

    # ── Critical Moments ─────────────────────────────────────
    all_criticals = []
    for sc in scorecards:
        for cf in sc.critical_failures:
            all_criticals.append(f"[{sc.run_id}] {cf}")

    if all_criticals:
        lines.append("-" * 70)
        lines.append("CRITICAL MOMENTS")
        lines.append("-" * 70)
        for c in all_criticals:
            lines.append(f"  🚨 {c}")
        lines.append("")

    # ── Likely Root Causes ───────────────────────────────────
    lines.append("-" * 70)
    lines.append("LIKELY ROOT CAUSES")
    lines.append("-" * 70)
    if batch_summary.top_failure_categories:
        for cat in batch_summary.top_failure_categories:
            lines.append(f"  → {cat} (consistently low scores)")
    elif meta_errors:
        lines.append("  → Infrastructure / Transport Failure (check Ollama status)")
        lines.append("  → Scenario Gating Conflict (check allowed_packs in agents.yaml)")
    else:
        lines.append("  No systematic failure patterns detected.")
    lines.append("")

    # ── Automated Review Team (APEX) ─────────────────────────
    reviewer_results = batch_summary.data.get("reviewer_results")
    reviewer_status = batch_summary.data.get("reviewer_status", "unknown")
    reviewer_error = batch_summary.data.get("reviewer_error")

    if reviewer_results and reviewer_status == "success":
        lines.append("-" * 70)
        lines.append("AUTOMATED REVIEW TEAM FINDINGS")
        lines.append("-" * 70)
        
        for role, result in reviewer_results.items():
            if role == "troy_patch": continue
            status_icon = "✅" if result.get("status") == "pass" else "⚠️" if result.get("status") == "warn" else "🚨"
            lines.append(f"  {status_icon} {role.replace('_', ' ').title()}: {result.get('summary', 'No summary provided.')}")
            if result.get("status") == "error":
                lines.append(f"     • 🚨 ERROR: {result.get('error', 'Unknown reviewer error')}")
            for finding in result.get("findings", []):
                lines.append(f"     • {finding}")
            lines.append("")
    elif reviewer_status == "error":
        lines.append("-" * 70)
        lines.append("AUTOMATED REVIEW TEAM FAILURE")
        lines.append("-" * 70)
        lines.append(f"  🚨 Error: {reviewer_error or 'Unknown analytic failure'}")
        lines.append("  The reviewer team encountered a technical error during analysis.")
        lines.append("")
    elif reviewer_status == "success":
        lines.append("-" * 70)
        lines.append("AUTOMATED REVIEW TEAM STATUS")
        lines.append("-" * 70)
        lines.append("  🔍 PARTIAL REVIEW GENERATED FROM STALLED SESSION")
        lines.append("  APEX analysis extracted insights despite the infrastructure stall.")
        lines.append("")
    elif meta_errors and not scorecards:
        lines.append("-" * 70)
        lines.append("AUTOMATED REVIEW TEAM STATUS")
        lines.append("-" * 70)
        lines.append("  ⚠️ REVIEW NOT EXECUTED")
        lines.append("  Check tool configuration for review_mode.")
        lines.append("")

    # ── Eval Contract Recap ──────────────────────────────────
    if all_meta:
        contract = all_meta[0].get("eval_contract")
        if contract:
            lines.append("-" * 70)
            lines.append("EFFECTIVE EVAL CONTRACT")
            lines.append("-" * 70)
            lines.append(f"  Must Collect:    {', '.join(contract.get('must_collect', []))}")
            lines.append(f"  Success Event:   {contract.get('success_event', 'N/A')}")
            lines.append(f"  Fail Conditions: {', '.join(contract.get('fail_conditions', []))}")
            lines.append("")

    # ── Troy Patch Candidate ─────────────────────────────────
    troy_patch = batch_summary.data.get("troy_patch")
    if troy_patch:
        lines.append("-" * 70)
        lines.append("TROY PROMPT PATCH CANDIDATE")
        lines.append("-" * 70)
        lines.append(f"  Rationale: {troy_patch.get('rationale', 'N/A')}")
        lines.append(f"  Risk Note: {troy_patch.get('risk_note', 'N/A')}")
        lines.append("")
        lines.append("  PATCH SEED:")
        lines.append("  " + "-" * 30)
        lines.append(troy_patch.get("patch_candidate", "No patch generated."))
        lines.append("  " + "-" * 30)
        lines.append("")
        lines.append("  Regression Scenarios:")
        for rs in troy_patch.get("regression_scenarios", []):
            lines.append(f"    • {rs}")
        lines.append("")

    # ── Suggested Persona Changes / KB Changes ───────────────
    low_cats = batch_summary.top_failure_categories
    
    if not reviewer_results:
        lines.append("-" * 70)
        lines.append("SUGGESTED PERSONA CHANGES (LEGACY)")
        lines.append("-" * 70)
        if not low_cats:
            lines.append("  No immediate persona changes recommended.")
        else:
            for cat in low_cats:
                lines.append(f"  → Review {cat} logic in system prompt.")
        lines.append("")

    # ── Suggested KB / Guardrail Changes ─────────────────────
    lines.append("-" * 70)
    lines.append("SUGGESTED KB / GUARDRAIL CHANGES")
    lines.append("-" * 70)
    if not low_cats:
        lines.append("  No KB/guardrail changes needed at this time.")
    else:
        if "compliance_safety" in low_cats:
            lines.append("  ⚠ PRIORITY: Review and strengthen safety guardrails")
            lines.append("    → Audit system prompt for information leak vectors")
        if "flow_naturalness" in low_cats:
            lines.append("  → Adjust response length constraints")
            lines.append("  → Review stop token configuration")
    lines.append("")

    lines.append("=" * 70)
    lines.append("END OF REVIEW PACKET")
    lines.append("=" * 70)

    return "\n".join(lines)


def save_review_packet(batch_id: str, packet_text: str) -> str:
    """Save the review packet to the batch directory."""
    batch_dir = os.path.join(VAULT_DIR, "evals", "batches", batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    path = os.path.join(batch_dir, "review_packet.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(packet_text)
    return path
