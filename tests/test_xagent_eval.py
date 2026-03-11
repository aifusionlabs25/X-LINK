"""
X-Agent Eval v1 — Smoke Tests
Validates: router, scenario loading, scoring rubric, transcript normalization,
batch aggregation, review packet generation, and error handling.
"""

import os
import sys
import json
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


# ── 1. Tool resolves through router ──────────────────────────

def test_eval_tool_resolves():
    from hub.router import resolve_tool
    tool = resolve_tool("xagent_eval")
    assert tool is not None
    assert tool.__class__.__name__ == "XAgentEvalTool"
    assert tool.key == "xagent_eval"


# ── 2. Scenario pack loads ────────────────────────────────────

def test_scenario_pack_loads():
    from tools.xagent_eval.scenario_bank import load_scenario_pack
    scenarios = load_scenario_pack("default_pack")
    assert len(scenarios) == 4
    assert all("scenario_id" in s for s in scenarios)
    assert all("title" in s for s in scenarios)
    assert all("opening_message" in s for s in scenarios)


def test_scenario_selection():
    from tools.xagent_eval.scenario_bank import select_scenarios
    selected = select_scenarios("default_pack", count=6, difficulty="mixed", seed=42)
    assert len(selected) == 6


def test_scenario_difficulty_filter():
    from tools.xagent_eval.scenario_bank import select_scenarios
    easy = select_scenarios("default_pack", count=3, difficulty="easy", seed=1)
    assert all(s.get("difficulty") == "easy" for s in easy)


def test_scenario_pack_list():
    from tools.xagent_eval.scenario_bank import list_packs
    packs = list_packs()
    assert "default_pack" in packs


# ── 3. Scoring rubric loads ──────────────────────────────────

def test_scoring_rubric_loads():
    from tools.xagent_eval.scoring import load_rubric
    rubric = load_rubric("default_v1")
    assert "categories" in rubric
    assert len(rubric["categories"]) == 9
    keys = [c["key"] for c in rubric["categories"]]
    assert "greeting_first_impression" in keys
    assert "compliance_safety" in keys
    assert "objection_handling" in keys


def test_scoring_rubric_weights():
    from tools.xagent_eval.scoring import load_rubric
    rubric = load_rubric("default_v1")
    total_weight = sum(c["weight"] for c in rubric["categories"])
    assert total_weight == 100


# ── 4. Transcript normalization ──────────────────────────────

def test_transcript_normalization():
    from tools.xagent_eval.transcript_normalizer import normalize_transcript
    raw = [
        {"turn": 1, "speaker": "test_user", "text": "Hello!"},
        {"turn": 2, "speaker": "agent_under_test", "text": "Hi there."},
        {"turn": 3, "speaker": "agent_under_test", "text": "How can I help?"},  # merge
        {"turn": 4, "speaker": "test_user", "text": "  [typing...]  "},  # cleaned
        {"turn": 5, "speaker": "test_user", "text": "Tell me about pricing."},
    ]
    normalized = normalize_transcript(raw)
    assert len(normalized) == 3  # merged same-speaker, cleaned empty
    assert normalized[0]["speaker"] == "test_user"
    assert normalized[1]["speaker"] == "agent_under_test"
    assert "How can I help?" in normalized[1]["text"]
    assert normalized[2]["speaker"] == "test_user"
    assert normalized[2]["turn"] == 3


def test_transcript_to_text():
    from tools.xagent_eval.transcript_normalizer import transcript_to_text
    turns = [
        {"turn": 1, "speaker": "test_user", "text": "Hello"},
        {"turn": 2, "speaker": "agent_under_test", "text": "Hi there"},
    ]
    text = transcript_to_text(turns)
    assert "[Turn 1] USER: Hello" in text
    assert "[Turn 2] AGENT: Hi there" in text


def test_transcript_stats():
    from tools.xagent_eval.transcript_normalizer import transcript_stats
    turns = [
        {"turn": 1, "speaker": "test_user", "text": "Hello world"},
        {"turn": 2, "speaker": "agent_under_test", "text": "Hi there, welcome."},
        {"turn": 3, "speaker": "test_user", "text": "Thanks"},
    ]
    stats = transcript_stats(turns)
    assert stats["total_turns"] == 3
    assert stats["user_turns"] == 2
    assert stats["agent_turns"] == 1


# ── 5. Batch summary aggregation ─────────────────────────────

def test_batch_aggregation():
    from tools.xagent_eval.schemas import EvalInputs, Scorecard, CategoryScore
    from tools.xagent_eval.batch_runner import aggregate_batch

    inputs = EvalInputs(target_agent="Morgan", scenario_pack="default_pack", runs=2)

    sc1 = Scorecard(run_id="r1", scenario_id="SC_COOP_001", target_agent="Morgan",
                    overall_score=85, pass_fail="PASS")
    sc1.categories = [CategoryScore(key="greeting_first_impression", label="Greeting", score=4, weight=10)]

    sc2 = Scorecard(run_id="r2", scenario_id="SC_SKEP_001", target_agent="Morgan",
                    overall_score=65, pass_fail="FAIL")
    sc2.categories = [CategoryScore(key="greeting_first_impression", label="Greeting", score=2, weight=10)]

    summary = aggregate_batch("batch_test", inputs, [sc1, sc2], ["r1", "r2"])
    assert summary.total_runs == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.pass_rate == 50.0
    assert summary.average_score == 75.0


# ── 6. Review packet generates ───────────────────────────────

def test_review_packet_generates():
    from tools.xagent_eval.schemas import BatchSummary, Scorecard
    from tools.xagent_eval.review_packet import generate_review_packet

    summary = BatchSummary(
        batch_id="test_batch", target_agent="Morgan",
        environment="prod", scenario_pack="default_pack",
        total_runs=3, passed=2, failed=1, pass_rate=66.7,
        average_score=72.5,
        category_averages={"greeting_first_impression": 4.0, "objection_handling": 2.5},
        top_failure_categories=["objection_handling"],
    )
    sc = Scorecard(run_id="r1", scenario_id="SC_SKEP_001", target_agent="Morgan",
                   overall_score=60, pass_fail="FAIL",
                   warnings=["Objection Handling: Failed to address pushback"])

    packet = generate_review_packet(summary, [sc], [{"scenario_id": "SC_SKEP_001", "title": "Skeptical"}])
    assert "REVIEW PACKET" in packet
    assert "Morgan" in packet
    assert "objection_handling" in packet
    assert "SUGGESTED PERSONA CHANGES" in packet


# ── 7. Invalid agent returns structured error ────────────────

def test_invalid_agent_error():
    import asyncio
    from tools.xagent_eval.tool import XAgentEvalTool
    tool = XAgentEvalTool()
    result = asyncio.run(tool.run(
        {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")},
        {"target_agent": ""}
    ))
    assert result.status == "error"
    assert "E_AGENT_NOT_FOUND" in str(result.data)


# ── 8. Invalid scenario pack returns structured error ────────

def test_invalid_scenario_pack_error():
    import asyncio
    from tools.xagent_eval.tool import XAgentEvalTool
    tool = XAgentEvalTool()
    result = asyncio.run(tool.run(
        {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")},
        {"target_agent": "Morgan", "scenario_pack": "nonexistent_pack"}
    ))
    assert result.status == "error"
    assert "E_SCENARIO_LOAD_FAILED" in str(result.data)


# ── 9. Schemas validate ──────────────────────────────────────

def test_eval_inputs_from_dict():
    from tools.xagent_eval.schemas import EvalInputs
    inputs = EvalInputs.from_dict({
        "target_agent": "Morgan",
        "runs": 5,
        "difficulty": "hard",
    })
    assert inputs.target_agent == "Morgan"
    assert inputs.runs == 5
    assert inputs.difficulty == "hard"
    assert inputs.environment == "prod"
    assert inputs.max_turns == 12


def test_scorecard_serialization():
    from tools.xagent_eval.schemas import Scorecard, CategoryScore
    sc = Scorecard(run_id="r1", scenario_id="sc1", target_agent="Morgan",
                   overall_score=82, pass_fail="PASS")
    sc.categories = [CategoryScore(key="k", label="L", score=4, weight=10)]
    d = sc.to_dict()
    assert isinstance(d, dict)
    json.dumps(d)  # Must be serializable
