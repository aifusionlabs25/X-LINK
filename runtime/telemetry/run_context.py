"""
X-LINK HUB v3 — Runtime: Telemetry Run Context
Provides run_id generation, timing, and context for every tool execution.
"""

import uuid
import time
import logging
from datetime import datetime
from typing import Optional


class RunContext:
    """Tracks a single tool execution run."""

    def __init__(self, tool_key: str, run_id: Optional[str] = None):
        self.tool_key = tool_key
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.logger = logging.getLogger(f"run.{tool_key}.{self.run_id}")

    def start(self):
        self.started_at = time.time()
        self.logger.info(f"Run started at {datetime.now().isoformat()}")

    def finish(self):
        self.completed_at = time.time()
        elapsed = (self.completed_at - (self.started_at or self.completed_at))
        self.logger.info(f"Run completed in {elapsed:.2f}s")

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "tool_key": self.tool_key,
            "run_id": self.run_id,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat() if self.started_at else None,
            "completed_at": datetime.fromtimestamp(self.completed_at).isoformat() if self.completed_at else None,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }
