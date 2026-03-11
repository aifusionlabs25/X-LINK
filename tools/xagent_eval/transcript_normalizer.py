"""
X-Agent Eval v1 — Transcript Normalizer
Converts raw transcript data into a stable, analysis-ready format.
"""

import re
import logging
from typing import List

logger = logging.getLogger("xagent_eval.normalizer")


def normalize_transcript(raw_turns: List[dict]) -> List[dict]:
    """
    Normalize raw transcript turns into the standard format:
    [{"turn": 1, "speaker": "test_user"|"agent_under_test", "text": "..."}]

    Handles:
    - Deduplication of consecutive same-speaker turns
    - Whitespace cleanup
    - Turn renumbering
    - Empty message removal
    """
    if not raw_turns:
        return []

    cleaned = []
    for turn in raw_turns:
        text = turn.get("text", "").strip()

        # Remove UI artifacts
        text = re.sub(r'\[typing\.\.\.\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[loading\]', '', text, flags=re.IGNORECASE)
        text = text.strip()

        if not text:
            continue

        speaker = turn.get("speaker", "unknown")
        if speaker not in ("test_user", "agent_under_test"):
            speaker = "agent_under_test"

        # Merge consecutive same-speaker turns
        if cleaned and cleaned[-1]["speaker"] == speaker:
            cleaned[-1]["text"] += f" {text}"
        else:
            cleaned.append({
                "speaker": speaker,
                "text": text,
                "timestamp": turn.get("timestamp"),
            })

    # Renumber turns
    result = []
    for i, entry in enumerate(cleaned):
        result.append({
            "turn": i + 1,
            "speaker": entry["speaker"],
            "text": entry["text"],
        })

    return result


def transcript_to_text(turns: List[dict]) -> str:
    """Convert normalized transcript to plain text format."""
    lines = []
    for t in turns:
        role = "USER" if t["speaker"] == "test_user" else "AGENT"
        lines.append(f"[Turn {t['turn']}] {role}: {t['text']}")
    return "\n\n".join(lines)


def transcript_stats(turns: List[dict]) -> dict:
    """Compute basic statistics about a transcript."""
    if not turns:
        return {"total_turns": 0, "user_turns": 0, "agent_turns": 0,
                "avg_agent_length": 0, "avg_user_length": 0}

    user_turns = [t for t in turns if t["speaker"] == "test_user"]
    agent_turns = [t for t in turns if t["speaker"] == "agent_under_test"]

    return {
        "total_turns": len(turns),
        "user_turns": len(user_turns),
        "agent_turns": len(agent_turns),
        "avg_agent_length": round(
            sum(len(t["text"]) for t in agent_turns) / max(1, len(agent_turns))
        ),
        "avg_user_length": round(
            sum(len(t["text"]) for t in user_turns) / max(1, len(user_turns))
        ),
    }
