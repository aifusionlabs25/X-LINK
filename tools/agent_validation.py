from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ValidationFamily:
    key: str
    label: str
    description: str
    default_channel_mode: str
    golden_pack_size: int
    release_gates: List[str] = field(default_factory=list)
    hard_fail_categories: List[str] = field(default_factory=list)


FAMILY_REGISTRY: Dict[str, ValidationFamily] = {
    "sales_discovery": ValidationFamily(
        key="sales_discovery",
        label="Sales / Discovery",
        description="Top-of-funnel sales, product positioning, qualification, and interest generation.",
        default_channel_mode="speak_first",
        golden_pack_size=6,
        release_gates=[
            "quick_regression",
            "deterministic_audit",
            "golden_pack",
            "live_pilot_review",
        ],
        hard_fail_categories=["compliance_safety", "greeting_script_adherence"],
    ),
    "support_service": ValidationFamily(
        key="support_service",
        label="Support / Service",
        description="Customer support, troubleshooting, account assistance, and service continuity.",
        default_channel_mode="user_first",
        golden_pack_size=6,
        release_gates=[
            "quick_regression",
            "deterministic_audit",
            "golden_pack",
            "live_pilot_review",
        ],
        hard_fail_categories=["compliance_safety", "accuracy_groundedness"],
    ),
    "executive_operator": ValidationFamily(
        key="executive_operator",
        label="Executive / Operator",
        description="Operations, planning, reporting, and task-running agents such as Sloane.",
        default_channel_mode="user_first",
        golden_pack_size=5,
        release_gates=[
            "quick_regression",
            "deterministic_audit",
            "workflow_validation",
            "approval_gate_review",
        ],
        hard_fail_categories=["compliance_safety", "strategic_progression"],
    ),
    "intake_qualification": ValidationFamily(
        key="intake_qualification",
        label="Intake / Qualification",
        description="Lead capture, intake, routing, and early qualification workflows.",
        default_channel_mode="user_first",
        golden_pack_size=5,
        release_gates=[
            "quick_regression",
            "deterministic_audit",
            "golden_pack",
            "live_pilot_review",
        ],
        hard_fail_categories=["compliance_safety", "strategic_progression"],
    ),
}


AGENT_FAMILY_OVERRIDES: Dict[str, str] = {
    "dani": "sales_discovery",
    "morgan": "sales_discovery",
    "sloane": "executive_operator",
}


def infer_validation_family(agent_slug: str, mission_request: str = "") -> ValidationFamily:
    slug = (agent_slug or "").strip().lower()
    if slug in AGENT_FAMILY_OVERRIDES:
        return FAMILY_REGISTRY[AGENT_FAMILY_OVERRIDES[slug]]

    text = f"{slug} {mission_request or ''}".lower()
    if any(term in text for term in ("support", "service", "troubleshoot", "ticket")):
        return FAMILY_REGISTRY["support_service"]
    if any(term in text for term in ("sloane", "ops", "operator", "briefing", "report")):
        return FAMILY_REGISTRY["executive_operator"]
    if any(term in text for term in ("intake", "qualify", "qualification", "lead capture", "routing")):
        return FAMILY_REGISTRY["intake_qualification"]
    return FAMILY_REGISTRY["sales_discovery"]


def build_validation_profile(agent_slug: str, mission_request: str = "", mode: str = "standard") -> Dict[str, Any]:
    family = infer_validation_family(agent_slug, mission_request)
    return {
        "family": family.key,
        "family_label": family.label,
        "description": family.description,
        "channel_mode": family.default_channel_mode,
        "golden_pack_size": family.golden_pack_size,
        "release_gates": list(family.release_gates),
        "hard_fail_categories": list(family.hard_fail_categories),
        "mode": mode or "standard",
    }


def _normalize_top_failures(summary: Dict[str, Any]) -> List[str]:
    failures = summary.get("top_failure_categories") or []
    return [str(item) for item in failures if item]


def _normalize_harness_artifacts(summary: Dict[str, Any]) -> List[str]:
    artifacts: List[str] = []
    for run in summary.get("runs", []) or []:
        artifacts.extend(str(item) for item in run.get("harness_artifacts", []) or [])
    return artifacts


def evaluate_release_readiness(
    validation_profile: Dict[str, Any],
    sh_lab_summary: Optional[Dict[str, Any]] = None,
    xagent_eval_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    family_key = validation_profile.get("family", "sales_discovery")
    family = FAMILY_REGISTRY.get(family_key, FAMILY_REGISTRY["sales_discovery"])
    summaries = [summary for summary in (sh_lab_summary, xagent_eval_summary) if summary]

    aggregate_failures: List[str] = []
    aggregate_artifacts: List[str] = []
    pass_rates: List[float] = []
    scores: List[float] = []

    for summary in summaries:
        aggregate_failures.extend(_normalize_top_failures(summary))
        aggregate_artifacts.extend(_normalize_harness_artifacts(summary))
        if summary.get("pass_rate") is not None:
            pass_rates.append(float(summary.get("pass_rate", 0.0)))
        if summary.get("average_score") is not None:
            scores.append(float(summary.get("average_score", 0.0)))

    unique_failures = list(dict.fromkeys(aggregate_failures))
    unique_artifacts = list(dict.fromkeys(aggregate_artifacts))
    average_score = round(sum(scores) / len(scores), 1) if scores else None
    average_pass_rate = round(sum(pass_rates) / len(pass_rates), 1) if pass_rates else None

    hard_fail_hit = any(cat in unique_failures for cat in family.hard_fail_categories)
    severe_artifact = any(
        any(token in artifact.lower() for token in ("timeout", "stall", "transport", "no_data"))
        for artifact in unique_artifacts
    )

    gates: List[Dict[str, Any]] = []
    gates.append(
        {
            "key": "quick_regression",
            "label": "Quick Regression",
            "status": "pass" if average_score is not None and average_score >= 70 else "fail",
            "detail": f"Average score {average_score}" if average_score is not None else "No scored runs found",
        }
    )
    gates.append(
        {
            "key": "deterministic_audit",
            "label": "Deterministic Audit",
            "status": "fail" if hard_fail_hit else "pass",
            "detail": (
                f"Hard-fail categories present: {', '.join(sorted(set(family.hard_fail_categories) & set(unique_failures)))}"
                if hard_fail_hit
                else "No family hard-fail categories detected"
            ),
        }
    )
    if "golden_pack" in family.release_gates:
        gates.append(
            {
                "key": "golden_pack",
                "label": "Golden Pack",
                "status": "pass" if average_pass_rate is not None and average_pass_rate >= 50 else "fail",
                "detail": (
                    f"Average pass rate {average_pass_rate}% across available runs"
                    if average_pass_rate is not None
                    else "No pass-rate data found"
                ),
            }
        )
    if "workflow_validation" in family.release_gates:
        gates.append(
            {
                "key": "workflow_validation",
                "label": "Workflow Validation",
                "status": "fail" if severe_artifact else "pass",
                "detail": (
                    f"Harness artifacts present: {', '.join(unique_artifacts[:3])}"
                    if severe_artifact
                    else "No severe workflow artifacts detected"
                ),
            }
        )
    if "approval_gate_review" in family.release_gates:
        gates.append(
            {
                "key": "approval_gate_review",
                "label": "Approval Gate Review",
                "status": "pass",
                "detail": "Approval-gated operator review required before wider rollout",
            }
        )
    if "live_pilot_review" in family.release_gates:
        gates.append(
            {
                "key": "live_pilot_review",
                "label": "Live Pilot Review",
                "status": "needs_review",
                "detail": "Use a monitored live pilot before broad promotion",
            }
        )

    auto_passable = all(gate["status"] == "pass" for gate in gates if gate["key"] != "live_pilot_review")
    recommendation = "soft_launch" if auto_passable and not severe_artifact else "revise"
    if hard_fail_hit:
        recommendation = "reject"

    return {
        "family": family.key,
        "family_label": family.label,
        "channel_mode": validation_profile.get("channel_mode", family.default_channel_mode),
        "average_score": average_score,
        "average_pass_rate": average_pass_rate,
        "top_failure_categories": unique_failures[:5],
        "harness_artifacts": unique_artifacts[:5],
        "gates": gates,
        "recommendation": recommendation,
    }
