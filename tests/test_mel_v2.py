import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import Scorecard
from tools.mel_v2.contracts import compile_contract
from tools.mel_v2.dani_audit import apply_dani_audit
from tools.mel_v2.validators import run_deterministic_checks


def test_compile_contract_uses_opening_message_as_user_first():
    agent_config = {
        "slug": "dani",
        "name": "Dani",
        "persona": (
            "You are Danny, an X Agents Sales Technician at AI Fusion Labs.\n"
            "Your first reply must begin by identifying you as Danny from AI Fusion Labs.\n"
            "When the system triggers your first turn, you speak first."
        ),
    }
    scenario = {
        "scenario_id": "DANI_USE_CASE_DIVE",
        "title": "Workflow Discovery",
        "opening_message": "Can X Agents actually lead a virtual tour?",
        "expected_good_outcomes": ["Agent answers the product question directly."],
    }

    contract = compile_contract("dani", agent_config, scenario)

    assert contract.start_mode == "user_first"
    assert contract.required_identity == "Danny from AI Fusion Labs"
    assert "Agent answers the product question directly." in contract.expected_good_outcomes


def test_deterministic_checks_flag_first_turn_dodge_and_early_contact():
    contract = compile_contract(
        "dani",
        {
            "slug": "dani",
            "name": "Dani",
            "persona": "Danny from AI Fusion Labs",
        },
        {"opening_message": "Can X Agents lead a virtual tour?"},
    )
    transcript = [
        {"speaker": "test_user", "text": "Can X Agents lead a virtual tour?"},
        {"speaker": "agent_under_test", "text": "Hi there, I'm Danny from AI Fusion Labs. How can I help you today?"},
        {"speaker": "test_user", "text": "What does pricing look like?"},
        {"speaker": "agent_under_test", "text": "What email should I send it to?"},
    ]

    findings = run_deterministic_checks(
        transcript=transcript,
        contract=contract,
        scenario={"opening_message": "Can X Agents lead a virtual tour?"},
    )

    assert any("dodge" in warning.lower() for warning in findings["warnings"])
    assert any("contact capture too early" in warning.lower() for warning in findings["warnings"])


def test_dani_audit_penalizes_repeated_identity_and_long_turns():
    scorecard = Scorecard(run_id="r1", scenario_id="s1", target_agent="dani", overall_score=88.0, pass_fail="PASS")
    transcript = [
        {"speaker": "test_user", "text": "What is this?"},
        {
            "speaker": "agent_under_test",
            "text": "Hi there, I'm Danny from AI Fusion Labs. X Agents can help with that. They can talk naturally. They can route next steps too.",
        },
        {"speaker": "test_user", "text": "Can you show a demo?"},
        {
            "speaker": "agent_under_test",
            "text": "I am Danny from AI Fusion Labs. What email should I send it to?",
        },
    ]

    audited = apply_dani_audit(scorecard, transcript)

    assert audited.overall_score < 88.0
    assert any("two-sentence limit" in warning.lower() for warning in audited.warnings)
    assert any("repeated self-identification" in warning.lower() for warning in audited.warnings)
