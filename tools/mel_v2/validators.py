from __future__ import annotations

import re
from typing import List, Dict, Any

from .contracts import ConversationContract


def _agent_turns(transcript: List[dict]) -> List[dict]:
    return [turn for turn in transcript if turn.get("speaker") == "agent_under_test"]


def _contains_contact_capture(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in ["email", "reach out", "contact you", "follow up", "what email"])


def _first_question_dodge(opening_message: str, reply: str) -> bool:
    lower = reply.lower()
    if "how can i help" in lower or "what can i help you with" in lower:
        return True
    opening_terms = {
        token
        for token in re.findall(r"[a-zA-Z]{4,}", opening_message.lower())
        if token not in {"what", "your", "with", "really", "style", "about"}
    }
    reply_terms = set(re.findall(r"[a-zA-Z]{4,}", lower))
    overlap = opening_terms.intersection(reply_terms)
    return len(overlap) == 0


def run_deterministic_checks(
    transcript: List[dict],
    contract: ConversationContract,
    scenario: Dict[str, Any],
) -> Dict[str, List[str]]:
    warnings: List[str] = []
    critical_failures: List[str] = []
    harness_artifacts: List[str] = []

    agents = _agent_turns(transcript)
    if not agents:
        critical_failures.append("No agent turns were captured.")
        return {
            "warnings": warnings,
            "critical_failures": critical_failures,
            "harness_artifacts": harness_artifacts,
        }

    first_reply = agents[0].get("text", "")
    opening_message = scenario.get("opening_message", "")

    if contract.required_identity and contract.required_identity.lower() not in first_reply.lower():
        critical_failures.append(
            f"Missing required first-turn identity: expected '{contract.required_identity}'."
        )

    if opening_message and _first_question_dodge(opening_message, first_reply):
        warnings.append("First reply appears to dodge the user's opening question.")

    repeated_identity = 0
    for reply in agents[1:]:
        if contract.required_identity and contract.required_identity.lower() in reply.get("text", "").lower():
            repeated_identity += 1
    if repeated_identity:
        warnings.append("Agent reintroduced identity after the first reply, which can feel unnatural.")

    early_contact = 0
    for reply in agents[:3]:
        if _contains_contact_capture(reply.get("text", "")):
            early_contact += 1
    if early_contact:
        warnings.append("Agent attempted contact capture too early in the conversation.")

    full_text = "\n".join(turn.get("text", "") for turn in agents).lower()
    for phrase in contract.forbidden_claim_phrases:
        if phrase in full_text:
            warnings.append(f"Ungrounded claim phrase detected: '{phrase}'.")

    overlong_turns = 0
    for reply in agents:
        text = reply.get("text", "")
        sentence_count = len([part for part in re.split(r"[.!?]+", text) if part.strip()])
        if sentence_count > 2:
            overlong_turns += 1
    if overlong_turns:
        warnings.append(f"Agent exceeded the two-sentence limit in {overlong_turns} turn(s).")

    return {
        "warnings": warnings,
        "critical_failures": critical_failures,
        "harness_artifacts": harness_artifacts,
    }
