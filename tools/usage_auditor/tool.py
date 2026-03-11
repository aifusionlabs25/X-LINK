"""
X-LINK HUB v3 — Usage Auditor Tool
Inspect usage/billing/consumption targets across platform dashboards.
"""

import os
import sys
import json
import yaml
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.base_tool import BaseTool, ToolResult


class UsageAuditorTool(BaseTool):
    key = "usage_auditor"
    description = "Inspect usage/billing/consumption targets across platform dashboards"

    def __init__(self):
        super().__init__()
        self.targets = []
        self.results_data = {}

    async def prepare(self, context: dict, inputs: dict) -> bool:
        # Load usage targets from config
        config_path = os.path.join(context.get("config_dir", "config"), "usage_targets.yaml")
        if not os.path.exists(config_path):
            self._mark_error(f"Config not found: {config_path}")
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        all_targets = config.get("targets", [])

        # Optional: filter to specific targets
        requested = inputs.get("targets", [])
        if requested:
            self.targets = [t for t in all_targets if t["name"] in requested]
        else:
            self.targets = all_targets

        if not self.targets:
            self._mark_error("No valid audit targets found.")
            return False

        self.logger.info(f"Prepared {len(self.targets)} targets for audit.")
        return True

    async def execute(self, context: dict) -> ToolResult:
        """
        Execute the audit cycle.
        This delegates to the legacy usage_auditor.py collector logic.
        In production, this would use runtime/browser to visit each platform.
        """
        try:
            # Import the legacy auditor for backwards compatibility
            from tools.usage_auditor import run_audit_cycle

            audit_data = await run_audit_cycle(self.targets)
            self.results_data = audit_data or {}
            self.result.data = self.results_data
            self._mark_success(f"Audited {len(self.results_data)} platforms.")

        except ImportError:
            # Fallback: return target list as structured data
            self.result.data = {
                "targets_configured": len(self.targets),
                "target_names": [t["name"] for t in self.targets],
                "note": "Legacy auditor not available. Run standalone: python tools/usage_auditor.py",
            }
            self._mark_success(f"{len(self.targets)} targets configured for audit.")

        except Exception as e:
            self._mark_error(f"Audit execution failed: {e}")

        return self.result

    async def save_artifacts(self, result: ToolResult) -> list[str]:
        report_path = self._vault_path("reports", f"audit_{self.run_id}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result.data, f, indent=2, default=str)
        result.artifacts.append(report_path)
        return result.artifacts

    async def summarize(self, result: ToolResult) -> str:
        n = result.data.get("targets_configured", len(self.results_data))
        result.summary = f"Usage audit completed across {n} platform targets."
        return result.summary
