"""
X-Agent Eval v1 — Schemas
Input/output contracts for the eval toolset.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvalContract:
    """Agent-specific evaluation agreement from agents.yaml."""
    allowed_packs: List[str] = field(default_factory=list)
    blocked_packs: List[str] = field(default_factory=list)
    user_archetypes: List[str] = field(default_factory=list)
    must_collect: List[str] = field(default_factory=list)
    success_event: str = "general_success"
    fail_conditions: List[str] = field(default_factory=list)
    close_strategy: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class EvalInputs:
    """Validated inputs for an eval run."""
    target_agent: str
    environment: str = "prod"
    scenario_pack: str = "default_pack"
    runs: int = 3
    difficulty: str = "mixed"
    scoring_rubric: str = "default_v1"
    transcript_mode: str = "dom_capture"
    browser_mode: bool = False
    max_turns: int = 12
    save_screenshots: bool = True
    seed: Optional[int] = None
    pass_threshold: int = 80
    review_mode: str = "full"
    rerun_failed_only: bool = False
    override_prompt: Optional[str] = None
    stress_test: bool = False  # Allows blocked packs

    @classmethod
    def from_dict(cls, d: dict) -> "EvalInputs":
        return cls(
            target_agent=d.get("target_agent", ""),
            environment=d.get("environment", "prod"),
            scenario_pack=d.get("scenario_pack", "default_pack"),
            runs=d.get("runs", 3),
            difficulty=d.get("difficulty", "mixed"),
            scoring_rubric=d.get("scoring_rubric", "default_v1"),
            transcript_mode=d.get("transcript_mode", "dom_capture"),
            browser_mode=bool(d.get("browser_mode", False)),
            max_turns=d.get("max_turns", 12),
            save_screenshots=d.get("save_screenshots", True),
            seed=d.get("seed"),
            pass_threshold=d.get("pass_threshold", 80),
            review_mode=d.get("review_mode", "full"),
            rerun_failed_only=bool(d.get("rerun_failed_only", False)),
            override_prompt=d.get("override_prompt"),
            stress_test=bool(d.get("stress_test", False))
        )


@dataclass
class TranscriptTurn:
    """A single turn in a normalized transcript."""
    turn: int
    speaker: str
    text: str
    timestamp: Optional[str] = None
    target_agent: Optional[str] = None
    environment: Optional[str] = None
    scenario_pack: Optional[str] = None
    scenario_id: Optional[str] = None
    run_id: Optional[str] = None
    batch_id: Optional[str] = None
    capture_source: str = "ollama_sim"
    transcript_status: str = "pending"
    completion_reason: Optional[str] = None
    fail_reason: Optional[str] = None


@dataclass
class CategoryScore:
    """Score for a single rubric category."""
    key: str
    label: str
    score: int         # 1-5
    weight: int
    notes: str = ""
    fail_flag: bool = False


@dataclass
class Scorecard:
    """Full scorecard for one eval run."""
    run_id: str
    scenario_id: str
    target_agent: str
    overall_score: float = 0.0
    pass_fail: str = "PENDING"      # PASS | PASS_WITH_WARNINGS | FAIL | FAIL_BLOCK_RELEASE
    classification: str = "not_classified" # valid_product_signal | review_runtime_failure | etc.
    categories: List[CategoryScore] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    critical_failures: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "target_agent": self.target_agent,
            "overall_score": self.overall_score,
            "pass_fail": self.pass_fail,
            "classification": self.classification,
            "categories": [
                {"key": c.key, "label": c.label, "score": c.score,
                 "weight": c.weight, "notes": c.notes, "fail_flag": c.fail_flag}
                for c in self.categories
            ],
            "warnings": self.warnings,
            "critical_failures": self.critical_failures,
        }


@dataclass
class RunMetadata:
    """Metadata for a single eval run."""
    run_id: str
    batch_id: str
    target_agent: str
    environment: str
    scenario_pack: str
    scenario_id: str
    scenario_title: str
    difficulty: str
    max_turns: int
    actual_turns: int = 0
    status: str = "pending"
    transcript_status: str = "pending"
    classification: str = "not_classified" # valid_product_signal | scenario_mismatch | etc.
    completion_reason: Optional[str] = None
    capture_source: str = "ollama_sim"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    eval_contract: Optional[dict] = None  # Logged contract
    is_reviewable: bool = False
    review_status: str = "skipped" # skipped | pending | success | error
    review_error: Optional[str] = None
    review_artifact_path: Optional[str] = None
    close_mode_triggered: bool = False
    close_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class BatchSummary:
    """Aggregate results for a batch of eval runs."""
    batch_id: str
    target_agent: str
    environment: str
    scenario_pack: str
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    average_score: float = 0.0
    category_averages: Dict[str, float] = field(default_factory=dict)
    top_failure_categories: List[str] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)
    runs: List[dict] = field(default_factory=list)
    verdict: str = "PENDING"
    reviewer_status: str = "skipped" # skipped | success | error
    reviewer_error: Optional[str] = None
    review_artifact_path: Optional[str] = None
    review_packet_text: Optional[str] = None
    reviewer_results: Dict[str, Any] = field(default_factory=dict)
    troy_patch: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── Error Codes ───────────────────────────────────────────────

class EvalError:
    AGENT_NOT_FOUND = "E_AGENT_NOT_FOUND"
    SESSION_LAUNCH_FAILED = "E_SESSION_LAUNCH_FAILED"
    TRANSCRIPT_CAPTURE_FAILED = "E_TRANSCRIPT_CAPTURE_FAILED"
    TRANSCRIPT_EMPTY = "E_TRANSCRIPT_EMPTY"
    SCENARIO_LOAD_FAILED = "E_SCENARIO_LOAD_FAILED"
    SCENARIO_MISMATCH = "E_SCENARIO_MISMATCH"
    MAX_TURNS_REACHED = "E_MAX_TURNS_REACHED"
    AGENT_RESPONSE_CUTOFF = "E_AGENT_RESPONSE_CUTOFF"
    SCORING_FAILED = "E_SCORING_FAILED"
    BATCH_ABORTED = "E_BATCH_ABORTED"
    TRANSPORT_SESSION_FAILURE = "E_TRANSPORT_SESSION_FAILURE"
    MISSING_USER_SLOT = "E_MISSING_USER_SLOT"
    AGENT_LOOP_CLOSE = "E_AGENT_LOOP_CLOSE"
    MAX_TURN_CLOSE_FAILURE = "E_MAX_TURN_CLOSE_FAILURE"
