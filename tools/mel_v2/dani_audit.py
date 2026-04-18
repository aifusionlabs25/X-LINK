from __future__ import annotations

import re
from typing import Dict, List

from tools.xagent_eval.schemas import Scorecard


def _agent_turns(transcript: List[dict]) -> List[dict]:
    return [turn for turn in transcript if turn.get("speaker") == "agent_under_test"]


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?]+", text or "") if part.strip()])


def apply_dani_audit(scorecard: Scorecard, transcript: List[dict]) -> Scorecard:
    agent_turns = _agent_turns(transcript)
    if not agent_turns:
        scorecard.critical_failures.append("Dani audit: no agent turns found.")
        scorecard.pass_fail = "FAIL_BLOCK_RELEASE"
        return scorecard

    first_reply = agent_turns[0].get("text", "")
    first_reply_lower = first_reply.lower()
    deterministic_penalty = 0

    if "danny from ai fusion labs" not in first_reply_lower:
        scorecard.warnings.append("Dani audit: first reply did not identify as Danny from AI Fusion Labs.")
        deterministic_penalty += 8

    long_turns = 0
    for turn in agent_turns:
        if _sentence_count(turn.get("text", "")) > 2:
            long_turns += 1
    if long_turns:
        scorecard.warnings.append(f"Dani audit: exceeded the two-sentence limit in {long_turns} turn(s).")
        deterministic_penalty += min(20, long_turns * 4)

    repeated_identity = 0
    for turn in agent_turns[1:]:
        if "danny from ai fusion labs" in turn.get("text", "").lower():
            repeated_identity += 1
    if repeated_identity:
        scorecard.warnings.append("Dani audit: repeated self-identification after the first reply.")
        deterministic_penalty += min(10, repeated_identity * 3)

    certainty_hits = 0
    certainty_terms = ["definitely", "absolutely", "seamlessly", "no lag"]
    for turn in agent_turns:
        text = turn.get("text", "").lower()
        for token in certainty_terms:
            if token in text:
                certainty_hits += 1
    if certainty_hits:
        scorecard.warnings.append("Dani audit: used overconfident certainty language.")
        deterministic_penalty += min(12, certainty_hits * 3)

    email_requests = 0
    repeated_email_confirmation = 0
    confirmed_email = False
    for turn in agent_turns:
        text = turn.get("text", "").lower()
        if "what email should i send it to" in text or "share an email address" in text:
            email_requests += 1
        if "i heard" in text and "is that right" in text:
            if confirmed_email:
                repeated_email_confirmation += 1
        if "next step is noted" in text or "the right email" in text:
            confirmed_email = True
    if email_requests > 1:
        scorecard.warnings.append("Dani audit: requested email more than once.")
        deterministic_penalty += min(10, (email_requests - 1) * 4)
    if repeated_email_confirmation:
        scorecard.warnings.append("Dani audit: repeated email confirmation after the handoff was already clear.")
        deterministic_penalty += min(10, repeated_email_confirmation * 5)

    follow_up_questions = 0
    soft_question_patterns = [
        "how does that sound",
        "what specific needs",
        "how do you see",
        "what are your main concerns",
        "does this align",
    ]
    for turn in agent_turns:
        text = turn.get("text", "").lower()
        if any(pattern in text for pattern in soft_question_patterns):
            follow_up_questions += 1
    if follow_up_questions >= 3:
        scorecard.warnings.append("Dani audit: overused generic follow-up questions instead of progressing cleanly.")
        deterministic_penalty += 8

    deterministic_penalty = min(18, deterministic_penalty)
    if deterministic_penalty:
        scorecard.overall_score = max(0.0, round(scorecard.overall_score - deterministic_penalty, 1))
        scorecard.harness_artifacts.append(f"Dani deterministic audit applied a {deterministic_penalty}-point adjustment.")

    if scorecard.overall_score < 80 and scorecard.pass_fail == "PASS":
        scorecard.pass_fail = "FAIL"

    return scorecard
