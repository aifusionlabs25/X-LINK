"""
X-LINK HUB v3 — Direct Briefing Tool
Transform tool outputs into executive/user-ready summaries.
This is a reporting/output layer, not a primary tool.
"""

import os
import sys
import json
import requests
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.base_tool import BaseTool, ToolResult

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-coder-next"

BRIEFING_PROMPT = (
    "You are Moneypenny (Sloane), the Chief of Staff for AI Fusion Labs. "
    "Synthesize the following operational data into a concise executive briefing. "
    "Include: key metrics, risk flags, and recommended actions. "
    "Tone: professional, sophisticated, British wit. No emojis. Keep it under 200 words."
)


class BriefingTool(BaseTool):
    key = "briefing"
    description = "Transform tool outputs into executive summaries"

    def __init__(self):
        super().__init__()
        self.source_tools = []
        self.output_format = "markdown"
        self.source_data = {}

    async def prepare(self, context: dict, inputs: dict) -> bool:
        self.source_tools = inputs.get("source_tools", [])
        self.output_format = inputs.get("format", "markdown")

        # Load latest reports from vault
        reports_dir = os.path.join(context.get("vault_dir", "vault"), "reports")
        if os.path.exists(reports_dir):
            for f in sorted(os.listdir(reports_dir), reverse=True):
                if f.endswith(".json"):
                    path = os.path.join(reports_dir, f)
                    with open(path, "r", encoding="utf-8") as fh:
                        self.source_data[f] = json.load(fh)
                    if len(self.source_data) >= 5:
                        break
        return True

    async def execute(self, context: dict) -> ToolResult:
        try:
            # Combine source data into a prompt
            data_str = json.dumps(self.source_data, indent=2, default=str)[:3000]

            payload = {
                "model": MODEL,
                "prompt": f"{BRIEFING_PROMPT}\n\nOperational Data:\n{data_str}\n\nBriefing:\n",
                "stream": False,
            }
            response = requests.post(OLLAMA_URL, json=payload, timeout=120)
            response.raise_for_status()

            briefing = response.json().get("response", "").strip()
            self.result.data = {
                "briefing": briefing,
                "sources": list(self.source_data.keys()),
                "format": self.output_format,
            }
            self._mark_success("Executive briefing synthesized.")

        except Exception as e:
            self._mark_error(f"Briefing generation failed: {e}")

        return self.result

    async def save_artifacts(self, result: ToolResult) -> list[str]:
        ext = "md" if self.output_format == "markdown" else "json"
        report_path = self._vault_path("reports", f"briefing_{self.run_id}.{ext}")

        if self.output_format == "markdown":
            content = f"# Executive Briefing\n"
            content += f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            content += result.data.get("briefing", "")
        else:
            content = json.dumps(result.data, indent=2)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        result.artifacts.append(report_path)
        return result.artifacts

    async def summarize(self, result: ToolResult) -> str:
        result.summary = result.data.get("briefing", "No briefing generated.")[:200]
        return result.summary
