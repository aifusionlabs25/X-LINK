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
MODEL = "llama3.2"


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
) -> str:
    """Build an Ollama prompt to score one category."""
    transcript_text = "\n".join(
        f"[{t['speaker']}]: {t['text']}" for t in transcript
    )
    criteria_text = "\n".join(f"  - {c}" for c in category.get("criteria", []))

    return f"""You are an expert evaluator for AI sales agents. Score the following transcript on ONE specific category.

SCENARIO: {scenario.get('title', 'Unknown')}
USER ROLE: {scenario.get('role', 'Unknown')}
DIFFICULTY: {scenario.get('difficulty', 'Unknown')}

TRANSCRIPT:
{transcript_text}

CATEGORY TO SCORE: {category['label']}
CRITERIA:
{criteria_text}

INSTRUCTIONS:
1. Score from 1 to 5 (1=terrible, 2=poor, 3=adequate, 4=good, 5=excellent)
2. Provide a 1-sentence note explaining your score
3. Set fail_flag to true ONLY if the agent critically failed this category

Respond ONLY with valid JSON, no other text:
{{"score": <1-5>, "notes": "<1 sentence>", "fail_flag": <true/false>}}"""


def score_category(
    transcript: List[dict],
    scenario: dict,
    category: dict,
) -> CategoryScore:
    """Score one category using Ollama."""
    prompt = build_scoring_prompt(transcript, scenario, category)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json().get("response", "").strip()

        # Parse JSON from response
        # Handle cases where Ollama wraps in markdown
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
) -> Scorecard:
    """Score an entire eval run across all rubric categories."""
    rubric = load_rubric(rubric_name)
    categories = rubric.get("categories", [])

    scorecard = Scorecard(
        run_id=run_id,
        scenario_id=scenario.get("scenario_id", "unknown"),
        target_agent=target_agent,
    )

    total_weighted = 0
    total_weight = 0

    for cat_def in categories:
        cat_score = score_category(transcript, scenario, cat_def)
        scorecard.categories.append(cat_score)

        # Weighted contribution (score is 1-5, normalize to 0-100)
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

    # Determine pass/fail
    if scorecard.critical_failures:
        scorecard.pass_fail = "FAIL_BLOCK_RELEASE"
    elif scorecard.overall_score >= pass_threshold:
        scorecard.pass_fail = "PASS"
    elif scorecard.overall_score >= pass_threshold - 10:
        scorecard.pass_fail = "PASS_WITH_WARNINGS"
    else:
        scorecard.pass_fail = "FAIL"

    return scorecard
