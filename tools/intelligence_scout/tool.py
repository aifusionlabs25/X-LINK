"""
X-LINK HUB v3 — Intelligence Scout Tool
Research, gather, compare, and synthesize intelligence.
Sub Scout (Scout Workers) is an internal capability, not a top-level entry.
"""

import os
import sys
import json
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.base_tool import BaseTool, ToolResult
from tools.intelligence_scout.synthesis import run_synthesis


class IntelligenceScoutTool(BaseTool):
    key = "intelligence_scout"
    description = "Research, gather, compare, and synthesize intelligence"

    def __init__(self):
        super().__init__()
        self.query = ""
        self.source = "keep_md"

    async def prepare(self, context: dict, inputs: dict) -> bool:
        self.query = inputs.get("query", "")
        self.source = inputs.get("source", "keep_md")
        # No strict validation — scout can run in discovery mode with no query
        return True

    async def execute(self, context: dict) -> ToolResult:
        try:
            analysis = await run_synthesis(
                source=self.source,
                query=self.query,
            )
            self.result.data = analysis
            self._mark_success(f"Intelligence synthesis complete from source: {self.source}")

        except Exception as e:
            self._mark_error(f"Scout execution failed: {e}")

        return self.result

    async def save_artifacts(self, result: ToolResult) -> list[str]:
        report_path = self._vault_path("intel", f"scout_{self.run_id}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result.data, f, indent=2, default=str)
        result.artifacts.append(report_path)
        return result.artifacts

    async def summarize(self, result: ToolResult) -> str:
        title = result.data.get("title", "Unknown")
        result.summary = f"Intelligence gathered: {title}"
        return result.summary
