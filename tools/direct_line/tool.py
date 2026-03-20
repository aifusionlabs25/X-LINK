"""
X-LINK HUB v3 — Direct Line Tool
Freeform command/input lane to Sloane via local Ollama.
"""

import os
import sys
import requests
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.base_tool import BaseTool, ToolResult

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-coder-next"

SYSTEM_PROMPT = (
    "You are Moneypenny (Sloane), the sophisticated and sharp AI Chief of Staff for 'AI Fusion Labs'. "
    "You are talking to the 'Founder' via the Direct Line. Your tone is professional, clever, and British. "
    "KNOWLEDGE: X Agents are high-fidelity AI Sales Technicians (like Dani, Morgan, Amy). "
    "The X-LINK HUB is the Founder's autonomous command center. "
    "Keep responses concise. NEVER use emojis."
)


class DirectLineTool(BaseTool):
    key = "direct_line"
    description = "Freeform conversational command lane to Sloane"

    def __init__(self):
        super().__init__()
        self.message = ""

    async def prepare(self, context: dict, inputs: dict) -> bool:
        self.message = inputs.get("message", "").strip()
        if not self.message:
            self._mark_error("No message provided.")
            return False
        return True

    async def execute(self, context: dict) -> ToolResult:
        try:
            payload = {
                "model": MODEL,
                "prompt": f"{SYSTEM_PROMPT}\n\nFounder: {self.message}\nMoneypenny:",
                "stream": False,
            }
            response = requests.post(OLLAMA_URL, json=payload, timeout=60)
            response.raise_for_status()

            reply = response.json().get("response", "").strip()
            self.result.data = {"reply": reply, "model": MODEL}
            self._mark_success(f"Sloane replied to Direct Line message.")

        except Exception as e:
            self._mark_error(f"Ollama request failed: {e}")

        return self.result

    async def save_artifacts(self, result: ToolResult) -> list[str]:
        log_path = self._vault_path("sessions", f"direct_line_{self.run_id}.md")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## Direct Line — {timestamp}\n"
        entry += f"**Founder:** {self.message}\n\n"
        entry += f"**Sloane:** {result.data.get('reply', '')}\n\n---\n\n"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
        result.artifacts.append(log_path)
        return result.artifacts

    async def summarize(self, result: ToolResult) -> str:
        result.summary = result.data.get("reply", "No reply generated.")
        return result.summary
