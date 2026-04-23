import os
import re
import yaml
import logging
from typing import Dict, Any
from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("architect.tool")

class PromptArchitectTool(BaseTool):
    """
    X-LINK Prompt Architect — Gives Hermes the "Hands" to surgically patch agents.yaml.
    Includes a strict YAML linter to ensure safe writes.
    """
    key: str = "architect"
    description: str = "Allows Hermes to surgically patch agents.yaml with built-in YAML safety linting."

    async def prepare(self, context: dict, inputs: dict) -> bool:
        self.agent_slug = inputs.get("agent_slug")
        self.target_field = inputs.get("target_field", "persona") # Default to patching persona
        self.new_content = inputs.get("new_content")
        
        if not self.agent_slug or not self.new_content:
            self._mark_error("Missing required parameters: 'agent_slug' and 'new_content'.")
            return False
            
        self.config_path = self._config_path("agents.yaml")
        return True

    async def execute(self, context: dict) -> ToolResult:
        if not os.path.exists(self.config_path):
            self._mark_error(f"Config file not found: {self.config_path}")
            return self.result

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                original_text = f.read()

            # Find the start of the agent block
            agent_pattern = r"(^\s*-\s*slug:\s*['\"]?" + re.escape(self.agent_slug) + r"['\"]?\s*\n.*?)^\s*" + re.escape(self.target_field) + r"\s*:\s*\|\s*\n(.*?)(?=\n\s*[a-zA-Z0-9_]+\s*:|\n\s*-\s*slug:|\Z)"
            
            match = re.search(agent_pattern, original_text, re.DOTALL | re.MULTILINE)
            
            if not match:
                self._mark_error(f"Failed to locate {self.agent_slug}'s '{self.target_field}' block for patching.")
                return self.result
                
            prefix = match.group(1)
            old_content = match.group(2)
            
            # Use fixed 4-space indent for the inner content
            indent = "    "
                    
            formatted_new_content = "\n".join([f"{indent}{line}" if line.strip() else "" for line in self.new_content.split("\n")])
            
            # The field itself needs 2-space indent
            replacement = f"{prefix}  {self.target_field}: |\n{formatted_new_content}\n"
            
            # Apply the patch to the full text
            patched_text = original_text[:match.start()] + replacement + original_text[match.end():]

            # 2. DRY-RUN LINTER: Does this break the YAML?
            try:
                parsed_yaml = yaml.safe_load(patched_text)
                if not isinstance(parsed_yaml, dict) or "agents" not in parsed_yaml:
                    raise yaml.YAMLError("Parsed YAML missing root 'agents' list.")
            except yaml.YAMLError as ye:
                self._mark_error(f"Linter Error: Proposed patch breaks YAML syntax. Write rejected.\nDetails: {ye}")
                self.result.data = {"error_code": "LINT_FAILED", "details": str(ye)}
                return self.result

            # 3. Write to disk
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(patched_text)
                
            self._mark_success(f"Successfully patched '{self.target_field}' for agent '{self.agent_slug}'. Linter passed.")
            self.result.data = {
                "agent_slug": self.agent_slug,
                "patched_field": self.target_field,
                "status": "success"
            }
            
        except Exception as e:
            self._mark_error(f"Architect Tool failed: {e}")

        return self.result

    async def summarize(self, result: ToolResult) -> str:
        if result.status == "error":
            return f"Patch failed: {', '.join(result.errors)}"
        return result.summary
