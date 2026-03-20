"""
X-Agent Eval v1 — Scoring Engine
Scores each eval run against the rubric using local Ollama.
"""

import os
import sys
import json
import yaml
import requests
import logging
from typing import List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import CategoryScore, Scorecard, TranscriptTurn

logger = logging.getLogger("xagent_eval.scoring")

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-coder-next"


def load_rubric(rubric_name: str = "default_v1") -> dict:
    """Load a scoring rubric from config."""
    path = os.path.join(ROOT_DIR, "config", "scoring_rubrics.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get(rubric_name, {})


def build_scoring_prompt(
    transcript: List[dict],
    scenario: dict,
    category: dict,
    contract: "EvalContract" = None,
) -> str:
    """Build an Ollama prompt to score one category."""
    transcript_text = "\n".join(
        f"[{t['speaker']}]: {t['text']}" for t in transcript
    )
    criteria_text = "\n".join(f"  - {c}" for c in category.get("criteria", []))

    contract_text = ""
    if contract:
        contract_text = (
            f"MUST COLLECT: {', '.join(contract.must_collect)}\n"
            f"SUCCESS EVENT: {contract.success_event}\n"
            f"FAIL CONDITIONS: {', '.join(contract.fail_conditions)}\n"
        )

    return f"""You are an expert evaluator for AI agents. Score the following transcript on ONE specific category.

SCENARIO: {scenario.get('title', 'Unknown')}
USER ROLE: {scenario.get('role', 'Unknown')}
DIFFICULTY: {scenario.get('difficulty', 'Unknown')}

{contract_text}

TRANSCRIPT:
{transcript_text}

CATEGORY TO SCORE: {category['label']}
CRITERIA:
{criteria_text}

INSTRUCTIONS:
1. Score from 1 to 5 (1=terrible, 2=poor, 3=adequate, 4=good, 5=excellent)
2. Provide a 1-sentence note explaining your score
3. Set fail_flag to true ONLY if the agent critically failed this category or violated a FAIL CONDITION.

Respond ONLY with valid JSON, no other text:
{{"score": <1-5>, "notes": "<1 sentence>", "fail_flag": <true/false>}}"""


def score_category(
    transcript: List[dict],
    scenario: dict,
    category: dict,
    contract: "EvalContract" = None,
) -> CategoryScore:
    """Score one category using Ollama."""
    prompt = build_scoring_prompt(transcript, scenario, category, contract)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json().get("response", "").strip()

        # Parse JSON from response
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        return CategoryScore(
            key=category["key"],
            label=category["label"],
            score=max(1, min(5, int(result.get("score", 3)))),
            weight=category.get("weight", 10),
            notes=result.get("notes", ""),
            fail_flag=bool(result.get("fail_flag", False)),
        )
    except Exception as e:
        logger.warning(f"Scoring failed for {category['key']}: {e}")
        return CategoryScore(
            key=category["key"],
            label=category["label"],
            score=3,
            weight=category.get("weight", 10),
            notes=f"Auto-scored (scoring error: {str(e)[:80]})",
            fail_flag=False,
        )


def score_run(
    run_id: str,
    target_agent: str,
    transcript: List[dict],
    scenario: dict,
    rubric_name: str = "default_v1",
    pass_threshold: int = 80,
    contract: "EvalContract" = None,
) -> Scorecard:
    """Score an entire eval run across all rubric categories."""
    rubric = load_rubric(rubric_name)
    categories = rubric.get("categories", [])

    scorecard = Scorecard(
        run_id=run_id,
        scenario_id=scenario.get("scenario_id", "unknown"),
        target_agent=target_agent,
    )

    # Initial classification
    scorecard.classification = "valid_product_signal"

    total_weighted = 0
    total_weight = 0

    for cat_def in categories:
        cat_score = score_category(transcript, scenario, cat_def, contract)
        scorecard.categories.append(cat_score)

        # Weighted contribution
        normalized = (cat_score.score / 5.0) * 100
        total_weighted += normalized * cat_score.weight
        total_weight += cat_score.weight

        # Track failures
        if cat_score.fail_flag:
            if cat_def.get("critical"):
                scorecard.critical_failures.append(
                    f"{cat_score.label}: {cat_score.notes}"
                )
            else:
                scorecard.warnings.append(
                    f"{cat_score.label}: {cat_score.notes}"
                )

    # Calculate overall score
    if total_weight > 0:
        scorecard.overall_score = round(total_weighted / total_weight, 1)

    # ── Endgame Penalty System ──
    # Penaly for repetitive CTA phrasing in final turns
    agent_turns = [t for t in transcript if t.get("speaker") == "agent_under_test"]
    if len(agent_turns) >= 3:
        last_turns = agent_turns[-3:]
        repeats = 0
        for i in range(len(last_turns) - 1):
            s1 = last_turns[i].get("text", "").lower()[-30:]
            s2 = last_turns[i+1].get("text", "").lower()[-30:]
            if s1 == s2 and len(s1) > 10:
                repeats += 1
        if repeats > 0:
            penalty = 10 * repeats
            scorecard.overall_score = max(0, scorecard.overall_score - penalty)
            scorecard.warnings.append(f"Repetition Penalty: -{penalty}% for repeated CTA phrasing.")

    # Determine pass/fail and classification
    is_partial = any(t.get("transcript_status") == "partial" for t in transcript)
    comp_reason = transcript[0].get("completion_reason") if transcript else None
    
    # ── Explicit Ending Classifications ──
    tx_text = "\n".join([t.get("text", "") for t in transcript]).lower()
    last_turns = transcript[-5:]
    agent_asks = [t for t in last_turns if t.get("speaker") == "agent_under_test"]
    user_replies = [t for t in last_turns if t.get("speaker") == "test_user"]
    
    # SALVAGE LOGIC: If it's a stall but we have meaningful turns, mark as partial_review
    if is_partial or comp_reason in ("agent_stalled", "transcript_failed", "response_cutoff"):
        if len(transcript) > 4:
            scorecard.overall_score = round(scorecard.overall_score, 1)
            scorecard.pass_fail = "PASS_WITH_WARNINGS" if scorecard.overall_score >= pass_threshold else "FAIL"
            scorecard.classification = "valid_product_signal" # Salvaged
            scorecard.warnings.append(f"Salvage Review: Session stalled ({comp_reason}), but sufficient data exists for partial analysis.")
        else:
            scorecard.pass_fail = "FAIL"
            scorecard.classification = "transport_session_failure"
            reason_msg = f"Session Failure: {comp_reason}" if comp_reason else "Partial transcript detected."
            scorecard.critical_failures.append(reason_msg)
    elif scorecard.critical_failures:
        scorecard.pass_fail = "FAIL_BLOCK_RELEASE"
    elif scorecard.overall_score >= pass_threshold:
        scorecard.pass_fail = "PASS"
        scorecard.classification = "valid_product_signal"
    else:
        # Bad ending classification for scored failures
        scorecard.pass_fail = "FAIL"
        
        # Heuristic classification
        if any("Repetition Penalty" in w for w in scorecard.warnings):
            scorecard.classification = "agent_loop_close"
        elif "turn_limit_proximity" in tx_text or len(transcript) >= (contract.max_turns if contract else 12) * 2 - 2:
            scorecard.classification = "max_turn_close_failure"
        elif any(kw in tx_text for kw in ["email", "phone", "number"]) and not any(kw in tx_text for kw in ["@", "555-", "415-"]):
            # Asked but never got identity data (heuristic)
            scorecard.classification = "missing_user_slot_response"
        else:
            scorecard.classification = "valid_product_signal"

    return scorecard

    return scorecard

    return scorecard
