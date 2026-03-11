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

    # ── Failed Runs ──────────────────────────────────────────
    failed_runs = [s for s in scorecards if s.pass_fail in ("FAIL", "FAIL_BLOCK_RELEASE")]
    if failed_runs:
        lines.append("-" * 70)
        lines.append("FAILED RUNS")
        lines.append("-" * 70)
        for sc in failed_runs:
            scenario = next((s for s in scenarios if s.get("scenario_id") == sc.scenario_id), {})
            lines.append(f"  Run {sc.run_id}:")
            lines.append(f"    Scenario:  {scenario.get('title', sc.scenario_id)}")
            lines.append(f"    Score:     {sc.overall_score}/100")
            lines.append(f"    Verdict:   {sc.pass_fail}")
            if sc.critical_failures:
                for cf in sc.critical_failures:
                    lines.append(f"    🚨 CRITICAL: {cf}")
            if sc.warnings:
                for w in sc.warnings:
                    lines.append(f"    ⚠  WARNING: {w}")
            lines.append("")
    else:
        lines.append("No failed runs.\n")

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
    else:
        lines.append("  No systematic failure patterns detected.")
    lines.append("")

    # ── Suggested Persona Changes ────────────────────────────
    lines.append("-" * 70)
    lines.append("SUGGESTED PERSONA CHANGES")
    lines.append("-" * 70)
    low_cats = batch_summary.top_failure_categories

    if "objection_handling" in low_cats:
        lines.append("  1. Strengthen objection handling in system prompt")
        lines.append("     → Add specific rebuttal patterns and evidence frameworks")
    if "role_fidelity" in low_cats:
        lines.append("  2. Reinforce character boundaries")
        lines.append("     → Add explicit persona guardrails and identity anchors")
    if "accuracy_groundedness" in low_cats:
        lines.append("  3. Expand knowledge base and add fact-checking constraints")
        lines.append("     → Reduce temperature or add RAG retrieval")
    if "greeting_first_impression" in low_cats:
        lines.append("  4. Refine opening sequence")
        lines.append("     → Test variations of greeting and first interaction")
    if not low_cats:
        lines.append("  No immediate persona changes recommended.")
        lines.append("  Agent performed within acceptable thresholds.")
    lines.append("")

    # ── Suggested KB / Guardrail Changes ─────────────────────
    lines.append("-" * 70)
    lines.append("SUGGESTED KB / GUARDRAIL CHANGES")
    lines.append("-" * 70)
    if "compliance_safety" in low_cats:
        lines.append("  ⚠ PRIORITY: Review and strengthen safety guardrails")
        lines.append("    → Audit system prompt for information leak vectors")
    if "flow_naturalness" in low_cats:
        lines.append("  → Adjust response length constraints")
        lines.append("  → Review stop token configuration")
    if not low_cats:
        lines.append("  No KB/guardrail changes needed at this time.")
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
