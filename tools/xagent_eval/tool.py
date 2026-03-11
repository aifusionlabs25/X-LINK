"""
X-LINK HUB v3 — X-Agent Eval Tool (v1)
Full implementation: scenario-based testing, transcript capture, scoring, review packets.
Text-first, deterministic. V1 uses Ollama simulation; browser mode reserved for v2.
"""

import os
import sys
import uuid
import json
import asyncio
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.base_tool import BaseTool, ToolResult
from tools.xagent_eval.schemas import EvalInputs, EvalError, Scorecard, BatchSummary
from tools.xagent_eval.scenario_bank import select_scenarios, load_scenario_pack
from tools.xagent_eval.batch_runner import (
    execute_simulated_run, save_run_artifacts,
    aggregate_batch, save_batch_artifacts,
)
from tools.xagent_eval.review_packet import generate_review_packet, save_review_packet

logger = logging.getLogger("xagent_eval.tool")


class XAgentEvalTool(BaseTool):
    key = "xagent_eval"
    description = "Automated X Agent test sessions, scoring, and review packets"

    def __init__(self):
        super().__init__()
        self.inputs: EvalInputs = None
        self.batch_id = str(uuid.uuid4())[:8]

    async def prepare(self, context: dict, inputs: dict) -> bool:
        self.inputs = EvalInputs.from_dict(inputs)

        if not self.inputs.target_agent:
            self._mark_error("No target_agent specified.")
            self.result.data = {"error_code": EvalError.AGENT_NOT_FOUND}
            return False

        # Validate scenario pack
        scenarios = load_scenario_pack(self.inputs.scenario_pack)
        if not scenarios:
            self._mark_error(f"Scenario pack '{self.inputs.scenario_pack}' not found or empty.")
            self.result.data = {"error_code": EvalError.SCENARIO_LOAD_FAILED}
            return False

        self.logger.info(
            f"Eval prepared: agent={self.inputs.target_agent}, "
            f"pack={self.inputs.scenario_pack}, runs={self.inputs.runs}, "
            f"difficulty={self.inputs.difficulty}"
        )
        return True

    async def execute(self, context: dict) -> ToolResult:
        """Execute the full eval batch: select scenarios, run sims, score, aggregate."""
        try:
            # Select scenarios
            scenarios = select_scenarios(
                pack_name=self.inputs.scenario_pack,
                count=self.inputs.runs,
                difficulty=self.inputs.difficulty,
                seed=self.inputs.seed,
            )

            if not scenarios:
                self._mark_error("No scenarios selected.")
                self.result.data = {"error_code": EvalError.SCENARIO_LOAD_FAILED}
                return self.result

            scorecards = []
            run_ids = []
            all_metadata = []

            for i, scenario in enumerate(scenarios):
                run_id = f"{self.batch_id}_{i+1:02d}"
                run_ids.append(run_id)

                self.logger.info(
                    f"Run {i+1}/{len(scenarios)}: {scenario.get('title', 'unknown')} "
                    f"(difficulty: {scenario.get('difficulty')})"
                )

                # Execute simulated run
                metadata, transcript, scorecard = await execute_simulated_run(
                    run_id=run_id,
                    batch_id=self.batch_id,
                    inputs=self.inputs,
                    scenario=scenario,
                )

                # Save run artifacts
                if scorecard:
                    artifacts = save_run_artifacts(
                        run_id=run_id,
                        batch_id=self.batch_id,
                        metadata=metadata,
                        transcript=transcript,
                        scorecard=scorecard,
                    )
                    metadata.artifacts = artifacts
                    scorecards.append(scorecard)

                all_metadata.append(metadata)

            # Aggregate batch
            batch_summary = aggregate_batch(
                batch_id=self.batch_id,
                inputs=self.inputs,
                scorecards=scorecards,
                run_ids=run_ids,
            )

            # Save batch artifacts
            batch_artifacts = save_batch_artifacts(self.batch_id, batch_summary)

            # Generate review packet
            packet_text = generate_review_packet(batch_summary, scorecards, scenarios)
            packet_path = save_review_packet(self.batch_id, packet_text)
            batch_artifacts.append(packet_path)

            # Populate result
            self.result.data = {
                "batch_id": self.batch_id,
                "target_agent": self.inputs.target_agent,
                "total_runs": len(scenarios),
                "passed": batch_summary.passed,
                "failed": batch_summary.failed,
                "pass_rate": batch_summary.pass_rate,
                "average_score": batch_summary.average_score,
                "verdict": batch_summary.verdict,
                "category_averages": batch_summary.category_averages,
                "top_failure_categories": batch_summary.top_failure_categories,
                "run_ids": run_ids,
            }
            self.result.artifacts = batch_artifacts

            self._mark_success(
                f"Eval batch complete: {batch_summary.passed}/{len(scenarios)} passed "
                f"({batch_summary.pass_rate}%), verdict={batch_summary.verdict}"
            )

        except Exception as e:
            self._mark_error(f"Batch execution failed: {e}")
            self.result.data = {"error_code": EvalError.BATCH_ABORTED, "error": str(e)}

        return self.result

    async def verify(self, result: ToolResult) -> bool:
        """Verify the batch produced valid artifacts."""
        if result.status != "success":
            return False
        if not result.artifacts:
            return False
        return True

    async def save_artifacts(self, result: ToolResult) -> list:
        """Artifacts were already saved during execute(). Return the list."""
        return result.artifacts

    async def summarize(self, result: ToolResult) -> str:
        """Produce human-readable summary."""
        data = result.data
        result.summary = (
            f"X-Agent Eval: {data.get('target_agent', '?')} — "
            f"{data.get('passed', 0)}/{data.get('total_runs', 0)} passed "
            f"({data.get('pass_rate', 0)}%), "
            f"avg score {data.get('average_score', 0)}/100, "
            f"verdict: {data.get('verdict', '?')}"
        )
        return result.summary
