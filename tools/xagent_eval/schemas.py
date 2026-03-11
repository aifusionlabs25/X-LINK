"""
X-Agent Eval v1 — Schemas
Input/output contracts for the eval toolset.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    max_turns: int = 12
    save_screenshots: bool = True
    seed: Optional[int] = None
    pass_threshold: int = 80

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
            max_turns=d.get("max_turns", 12),
            save_screenshots=d.get("save_screenshots", True),
            seed=d.get("seed"),
            pass_threshold=d.get("pass_threshold", 80),
        )


@dataclass
class TranscriptTurn:
    """A single turn in a normalized transcript."""
    turn: int
    speaker: str       # "test_user" or "agent_under_test"
    text: str
    timestamp: Optional[str] = None


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
    scenario_id: str
    scenario_title: str
    difficulty: str
    max_turns: int
    actual_turns: int = 0
    status: str = "pending"         # pending | running | success | error
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)

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
    verdict: str = "PENDING"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── Error Codes ───────────────────────────────────────────────

class EvalError:
    AGENT_NOT_FOUND = "E_AGENT_NOT_FOUND"
    SESSION_LAUNCH_FAILED = "E_SESSION_LAUNCH_FAILED"
    TRANSCRIPT_CAPTURE_FAILED = "E_TRANSCRIPT_CAPTURE_FAILED"
    TRANSCRIPT_EMPTY = "E_TRANSCRIPT_EMPTY"
    SCENARIO_LOAD_FAILED = "E_SCENARIO_LOAD_FAILED"
    MAX_TURNS_REACHED = "E_MAX_TURNS_REACHED"
    SCORING_FAILED = "E_SCORING_FAILED"
    BATCH_ABORTED = "E_BATCH_ABORTED"
