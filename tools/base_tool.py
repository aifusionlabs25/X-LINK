"""
X-LINK HUB v3 — Base Tool Contract
Every tool in the HUB must implement this interface.
"""

import os
import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ToolResult:
    """Standardized result from any tool execution."""

    def __init__(self, tool_key: str, run_id: str):
        self.tool_key = tool_key
        self.run_id = run_id
        self.status = "pending"          # pending | running | success | error
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.data: Dict[str, Any] = {}
        self.artifacts: list[str] = []   # list of saved file paths
        self.errors: list[str] = []
        self.summary: str = ""

    def to_dict(self) -> dict:
        return {
            "tool_key": self.tool_key,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "data": self.data,
            "artifacts": self.artifacts,
            "errors": self.errors,
            "summary": self.summary,
        }


class BaseTool(ABC):
    """
    Abstract base class for all HUB tools.

    Contract:
        prepare()        → validate inputs and set up context
        execute()        → run the tool's core logic
        verify()         → check success criteria
        save_artifacts() → persist outputs to vault
        summarize()      → produce structured summary
    """

    key: str = "base"
    description: str = ""

    def __init__(self):
        self.run_id = str(uuid.uuid4())[:8]
        self.logger = logging.getLogger(f"tool.{self.key}")
        self.result = ToolResult(tool_key=self.key, run_id=self.run_id)
        self.vault_dir = os.path.join(ROOT_DIR, "vault")
        self.config_dir = os.path.join(ROOT_DIR, "config")

    # ── Lifecycle ──────────────────────────────────────────────

    @abstractmethod
    async def prepare(self, context: dict, inputs: dict) -> bool:
        """Validate inputs and prepare runtime dependencies. Return True if ready."""
        ...

    @abstractmethod
    async def execute(self, context: dict) -> ToolResult:
        """Run the tool's primary logic. Must populate self.result."""
        ...

    async def verify(self, result: ToolResult) -> bool:
        """Optional: check success criteria. Default passes if no errors."""
        return result.status == "success" and len(result.errors) == 0

    async def save_artifacts(self, result: ToolResult) -> list[str]:
        """Optional: persist outputs. Default is no-op."""
        return result.artifacts

    async def summarize(self, result: ToolResult) -> str:
        """Optional: produce a human-readable summary. Default returns result.summary."""
        return result.summary

    # ── Helpers ────────────────────────────────────────────────

    def _vault_path(self, *parts) -> str:
        """Build a path under the vault directory."""
        path = os.path.join(self.vault_dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def _config_path(self, filename: str) -> str:
        """Build a path under the config directory."""
        return os.path.join(self.config_dir, filename)

    def _mark_started(self):
        self.result.status = "running"
        self.result.started_at = datetime.now().isoformat()

    def _mark_success(self, summary: str = ""):
        self.result.status = "success"
        self.result.completed_at = datetime.now().isoformat()
        self.result.summary = summary

    def _mark_error(self, error: str):
        self.result.status = "error"
        self.result.completed_at = datetime.now().isoformat()
        self.result.errors.append(error)

    # ── Runner (convenience) ──────────────────────────────────

    async def run(self, context: dict, inputs: dict) -> ToolResult:
        """Full lifecycle execution: prepare → execute → verify → artifacts → summarize."""
        self.logger.info(f"[{self.key}] Run {self.run_id} starting...")
        self._mark_started()

        try:
            ready = await self.prepare(context, inputs)
            if not ready:
                self._mark_error("Prepare step failed — inputs invalid or deps missing.")
                return self.result

            result = await self.execute(context)

            if result.status != "error":
                verified = await self.verify(result)
                if not verified:
                    self._mark_error("Verification failed.")
                else:
                    await self.save_artifacts(result)
                    await self.summarize(result)

        except Exception as e:
            self._mark_error(f"Unhandled exception: {e}")
            self.logger.error(f"[{self.key}] Run {self.run_id} failed: {e}")

        self.logger.info(f"[{self.key}] Run {self.run_id} finished: {self.result.status}")
        return self.result
