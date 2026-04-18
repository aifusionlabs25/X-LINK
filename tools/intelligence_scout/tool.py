"""
Legacy Intel Scout wrapper.

This compatibility wrapper now exists only so stale imports fail closed with a
clear message instead of trying to run removed behavior.
"""

from tools.base_tool import BaseTool, ToolResult


class IntelligenceScoutTool(BaseTool):
    key = "intelligence_scout"
    description = "Retired legacy wrapper for the old Intel Scout lane"

    async def prepare(self, context: dict, inputs: dict) -> bool:
        return True

    async def execute(self, context: dict) -> ToolResult:
        self.result.data = {
            "status": "retired",
            "message": "The legacy Intel Scout lane was retired. Use Trinity search, Browser Scout, or Scout Workers instead.",
        }
        self._mark_error(self.result.data["message"])
        return self.result
