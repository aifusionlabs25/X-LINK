"""
X-Agent Eval v1 — Batch Runner
Executes multiple eval runs, aggregates results, and produces batch summaries.
"""

import os
import sys
import uuid
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import (
    EvalInputs, RunMetadata, BatchSummary, Scorecard, EvalError,
)
from tools.xagent_eval.scenario_bank import select_scenarios
from tools.xagent_eval.transcript_normalizer import normalize_transcript, transcript_to_text, transcript_stats
from tools.xagent_eval.scoring import score_run

logger = logging.getLogger("xagent_eval.batch_runner")

VAULT_DIR = os.path.join(ROOT_DIR, "vault")


def save_run_artifacts(
    run_id: str,
    batch_id: str,
    metadata: RunMetadata,
    transcript: List[dict],
    scorecard: Scorecard,
) -> List[str]:
    """Save all artifacts for a single run."""
    run_dir = os.path.join(VAULT_DIR, "evals", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)
    saved = []

    # metadata.json
    meta_path = os.path.join(run_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata.to_dict(), f, indent=2)
    saved.append(meta_path)

    # transcript.json
    tx_json_path = os.path.join(run_dir, "transcript.json")
    with open(tx_json_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2)
    saved.append(tx_json_path)

    # transcript.txt
    tx_text_path = os.path.join(run_dir, "transcript.txt")
    with open(tx_text_path, "w", encoding="utf-8") as f:
        f.write(transcript_to_text(transcript))
    saved.append(tx_text_path)

    # scorecard.json
    sc_path = os.path.join(run_dir, "scorecard.json")
    with open(sc_path, "w", encoding="utf-8") as f:
        json.dump(scorecard.to_dict(), f, indent=2)
    saved.append(sc_path)

    return saved


def aggregate_batch(
    batch_id: str,
    inputs: EvalInputs,
    scorecards: List[Scorecard],
    run_ids: List[str],
) -> BatchSummary:
    """Aggregate multiple scorecards into a batch summary."""
    summary = BatchSummary(
        batch_id=batch_id,
        target_agent=inputs.target_agent,
        environment=inputs.environment,
        scenario_pack=inputs.scenario_pack,
        total_runs=len(scorecards),
        run_ids=run_ids,
    )

    if not scorecards:
        summary.verdict = "NO_DATA"
        return summary

    # Counts
    summary.passed = sum(1 for s in scorecards if s.pass_fail in ("PASS", "PASS_WITH_WARNINGS"))
    summary.failed = summary.total_runs - summary.passed
    summary.pass_rate = round((summary.passed / summary.total_runs) * 100, 1) if summary.total_runs > 0 else 0
    summary.average_score = round(sum(s.overall_score for s in scorecards) / len(scorecards), 1)

    # Category averages
    cat_scores = {}
    cat_counts = {}
    for sc in scorecards:
        for cat in sc.categories:
            if cat.key not in cat_scores:
                cat_scores[cat.key] = 0
                cat_counts[cat.key] = 0
            cat_scores[cat.key] += cat.score
            cat_counts[cat.key] += 1

    summary.category_averages = {
        k: round(v / cat_counts[k], 2)
        for k, v in cat_scores.items()
    }

    # Top failure categories (score < 3)
    low_cats = sorted(summary.category_averages.items(), key=lambda x: x[1])
    summary.top_failure_categories = [k for k, v in low_cats if v < 3.0][:3]

    # Verdict
    has_block = any(s.pass_fail == "FAIL_BLOCK_RELEASE" for s in scorecards)
    if has_block:
        summary.verdict = "NO-SHIP"
    elif summary.pass_rate >= 80:
        summary.verdict = "SHIP"
    elif summary.pass_rate >= 60:
        summary.verdict = "CONDITIONAL"
    else:
        summary.verdict = "NO-SHIP"

    return summary


def save_batch_artifacts(batch_id: str, summary: BatchSummary) -> List[str]:
    """Save batch-level artifacts."""
    batch_dir = os.path.join(VAULT_DIR, "evals", "batches", batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    saved = []

    # batch_summary.json
    json_path = os.path.join(batch_dir, "batch_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, indent=2)
    saved.append(json_path)

    # batch_summary.txt
    txt_path = os.path.join(batch_dir, "batch_summary.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"X-AGENT EVAL — BATCH SUMMARY\n")
        f.write(f"{'='*50}\n")
        f.write(f"Batch ID:       {summary.batch_id}\n")
        f.write(f"Target Agent:   {summary.target_agent}\n")
        f.write(f"Environment:    {summary.environment}\n")
        f.write(f"Scenario Pack:  {summary.scenario_pack}\n")
        f.write(f"Total Runs:     {summary.total_runs}\n")
        f.write(f"Passed:         {summary.passed}\n")
        f.write(f"Failed:         {summary.failed}\n")
        f.write(f"Pass Rate:      {summary.pass_rate}%\n")
        f.write(f"Average Score:  {summary.average_score}\n")
        f.write(f"Verdict:        {summary.verdict}\n")
        f.write(f"\nCategory Averages:\n")
        for k, v in summary.category_averages.items():
            f.write(f"  {k}: {v}/5.0\n")
        if summary.top_failure_categories:
            f.write(f"\nTop Failure Areas:\n")
            for cat in summary.top_failure_categories:
                f.write(f"  ⚠ {cat}\n")
    saved.append(txt_path)

    return saved


async def execute_simulated_run(
    run_id: str,
    batch_id: str,
    inputs: EvalInputs,
    scenario: dict,
) -> tuple:
    """
    Execute a single eval run using text-based simulation.
    For V1, this uses Ollama to simulate agent responses instead of live browser.
    Returns (metadata, transcript, scorecard).
    """
    import requests

    OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

    metadata = RunMetadata(
        run_id=run_id,
        batch_id=batch_id,
        target_agent=inputs.target_agent,
        environment=inputs.environment,
        scenario_id=scenario.get("scenario_id", "unknown"),
        scenario_title=scenario.get("title", "Unknown"),
        difficulty=scenario.get("difficulty", "mixed"),
        max_turns=inputs.max_turns,
        started_at=datetime.now().isoformat(),
    )

    transcript = []
    conversation = []

    # Agent system prompt
    agent_prompt = (
        f"You are {inputs.target_agent}, an X-Agent AI Sales Technician for AI Fusion Labs. "
        f"You are having a sales conversation. Stay in character. Be professional and engaging. "
        f"Keep responses to 2-3 sentences. Do not break character."
    )

    # Build the scenario twists lookup
    twists = {}
    for tw in scenario.get("twists", []):
        twists[tw.get("turn", 0)] = tw.get("injection", "")

    try:
        # Start with user's opening message
        user_msg = scenario.get("opening_message", "Hello.")

        for turn_num in range(1, inputs.max_turns + 1):
            # Check for twist injection
            if turn_num in twists and turn_num > 1:
                user_msg = twists[turn_num]

            # Record user turn (skip turn 1 inject on first iteration since opening is user)
            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "test_user",
                "text": user_msg,
            })
            conversation.append(f"User: {user_msg}")

            # Generate agent response
            conv_text = "\n".join(conversation)
            prompt = f"{agent_prompt}\n\n[CONVERSATION]\n{conv_text}\n{inputs.target_agent}:"

            response = requests.post(OLLAMA_URL, json={
                "model": "llama3.2",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.6, "stop": ["User:", "\n\n"]},
            }, timeout=60)

            agent_reply = response.json().get("response", "").strip()
            if not agent_reply:
                agent_reply = "I appreciate your interest. How can I help you today?"

            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "agent_under_test",
                "text": agent_reply,
            })
            conversation.append(f"{inputs.target_agent}: {agent_reply}")

            # Generate next user response (simulate the scenario user)
            user_profile = scenario.get("user_profile", {})
            user_context = user_profile.get("context", "A prospect visiting the website.")
            user_role = scenario.get("role", "cooperative_user")

            # Check if we have a twist for next turn
            next_turn = turn_num + 1
            if next_turn in twists:
                user_msg = twists[next_turn]
                continue

            # Otherwise generate a contextual follow-up
            user_gen_prompt = (
                f"You are {user_profile.get('name', 'a prospect')}. {user_context}\n"
                f"Role: {user_role}.\n"
                f"Continue this conversation naturally based on the agent's last reply. "
                f"Keep your response to 1-2 sentences. Stay in character as a {user_role}.\n\n"
                f"[CONVERSATION]\n{conv_text}\n{inputs.target_agent}: {agent_reply}\n"
                f"{user_profile.get('name', 'User')}:"
            )

            user_response = requests.post(OLLAMA_URL, json={
                "model": "llama3.2",
                "prompt": user_gen_prompt,
                "stream": False,
                "options": {"temperature": 0.7, "stop": [f"{inputs.target_agent}:", "\n\n"]},
            }, timeout=60)

            user_msg = user_response.json().get("response", "").strip()
            if not user_msg:
                user_msg = "Tell me more."

        metadata.status = "success"
        metadata.actual_turns = len(transcript)

    except Exception as e:
        metadata.status = "error"
        metadata.error_code = EvalError.SESSION_LAUNCH_FAILED
        metadata.error_message = str(e)
        logger.error(f"Run {run_id} failed: {e}")

    metadata.completed_at = datetime.now().isoformat()

    # Normalize and score
    normalized = normalize_transcript(transcript)
    scorecard = None

    if metadata.status == "success" and normalized:
        try:
            scorecard = score_run(
                run_id=run_id,
                target_agent=inputs.target_agent,
                transcript=normalized,
                scenario=scenario,
                rubric_name=inputs.scoring_rubric,
                pass_threshold=inputs.pass_threshold,
            )
        except Exception as e:
            metadata.error_code = EvalError.SCORING_FAILED
            metadata.error_message = str(e)
            logger.error(f"Scoring failed for run {run_id}: {e}")

    return metadata, normalized, scorecard
