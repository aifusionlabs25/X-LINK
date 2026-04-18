import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


from tools.agent_validation import build_validation_profile, evaluate_release_readiness, infer_validation_family


def test_infer_validation_family_uses_known_overrides():
    family = infer_validation_family("dani")
    assert family.key == "sales_discovery"
    assert family.default_channel_mode == "speak_first"


def test_infer_validation_family_uses_request_signal_for_ops():
    family = infer_validation_family("nova", "prepare a daily ops report for the team")
    assert family.key == "executive_operator"


def test_release_readiness_marks_sales_soft_launch_when_core_gates_pass():
    profile = build_validation_profile("dani", "Run a release check")
    sh_lab_summary = {
        "average_score": 76.0,
        "pass_rate": 50.0,
        "top_failure_categories": ["flow_naturalness"],
        "runs": [{"harness_artifacts": []}],
    }
    readiness = evaluate_release_readiness(profile, sh_lab_summary=sh_lab_summary)

    assert readiness["recommendation"] == "soft_launch"
    assert readiness["gates"][0]["status"] == "pass"
    assert readiness["gates"][1]["status"] == "pass"


def test_release_readiness_rejects_on_family_hard_fail():
    profile = build_validation_profile("dani", "Run a release check")
    sh_lab_summary = {
        "average_score": 82.0,
        "pass_rate": 80.0,
        "top_failure_categories": ["compliance_safety"],
        "runs": [{"harness_artifacts": []}],
    }
    readiness = evaluate_release_readiness(profile, sh_lab_summary=sh_lab_summary)

    assert readiness["recommendation"] == "reject"
    deterministic_gate = next(g for g in readiness["gates"] if g["key"] == "deterministic_audit")
    assert deterministic_gate["status"] == "fail"
