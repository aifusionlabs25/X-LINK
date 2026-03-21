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
from tools.xagent_eval.schemas import (
    EvalInputs, EvalError, Scorecard, BatchSummary, RunMetadata,
    EvalContract
)
from tools.xagent_eval.scenario_bank import select_scenarios, load_scenario_pack
from tools.xagent_eval.batch_runner import (
    execute_simulated_run, save_run_artifacts,
    aggregate_batch, save_batch_artifacts,
)
from tools.xagent_eval.scoring import score_run
from tools.xagent_eval.review_packet import generate_review_packet, save_review_packet
from tools.xagent_eval.reviewer_runner import ReviewerRunner
from tools.xagent_eval.review_team import ReviewTeam
from tools.xagent_eval.prompt_patch_generator import PromptPatchGenerator

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

        # Load agent eval contract
        try:
            import yaml
            agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
            with open(agents_path, "r", encoding="utf-8") as f:
                agents_data = yaml.safe_load(f)
            
            self.agent_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == self.inputs.target_agent), None)
            if not self.agent_conf:
                self._mark_error(f"Agent '{self.inputs.target_agent}' not found in agents.yaml.")
                self.result.data = {"error_code": EvalError.AGENT_NOT_FOUND}
                return False

            eval_block = self.agent_conf.get("eval", {})
            self.contract = EvalContract(
                allowed_packs=eval_block.get("allowed_packs", []),
                blocked_packs=eval_block.get("blocked_packs", []),
                user_archetypes=eval_block.get("user_archetypes", []),
                must_collect=eval_block.get("must_collect", []),
                success_event=eval_block.get("success_event", "general_success"),
                fail_conditions=eval_block.get("fail_conditions", []),
                close_strategy=self.agent_conf.get("close_strategy", {})
            )
        except Exception as e:
            self._mark_error(f"Failed to load eval contract: {e}")
            self.result.data = {"error_code": EvalError.BATCH_ABORTED}
            return False

        self.logger.info(
            f"Eval prepared: agent={self.inputs.target_agent}, "
            f"pack={self.inputs.scenario_pack}, runs={self.inputs.runs}, "
            f"difficulty={self.inputs.difficulty}"
        )
        return True
    async def execute(self, context: dict, progress_callback=None) -> ToolResult:
        """Execute the full eval batch: select scenarios, run sims, score, aggregate."""
        from tools.xagent_eval.transcript_capture import LiveBrowserCapture

        try:
            # ── 1. Hard-Gating Scenario Pack Verification ────────
            is_mismatch = False
            mismatch_reason = ""
            
            if not self.inputs.stress_test:
                if self.contract.allowed_packs and self.inputs.scenario_pack not in self.contract.allowed_packs:
                    is_mismatch = True
                    mismatch_reason = (
                        f"Scenario pack '{self.inputs.scenario_pack}' is not in allowed_packs for {self.inputs.target_agent}. "
                        f"Allowed: {self.contract.allowed_packs}"
                    )
                elif self.inputs.scenario_pack in self.contract.blocked_packs:
                    is_mismatch = True
                    mismatch_reason = f"Scenario pack '{self.inputs.scenario_pack}' is BLOCKED for {self.inputs.target_agent}."

            # ── 2. Handle Scenario Mismatch (Fallback Path) ──────
            if is_mismatch:
                self._mark_error(mismatch_reason)
                metadata = RunMetadata(
                    run_id=f"{self.batch_id}_MISMATCH",
                    batch_id=self.batch_id,
                    target_agent=self.inputs.target_agent,
                    environment=self.inputs.environment,
                    scenario_pack=self.inputs.scenario_pack,
                    scenario_id="GATING_MISMATCH",
                    scenario_title="Scenario Gating Error",
                    difficulty=self.inputs.difficulty,
                    max_turns=0,
                    status="error",
                    classification="scenario_mismatch",
                    error_code=EvalError.SCENARIO_MISMATCH,
                    error_message=mismatch_reason,
                    started_at=datetime.now().isoformat(),
                    completed_at=datetime.now().isoformat(),
                    eval_contract=self.contract.to_dict()
                )
                
                # Save just the metadata so Hub can see it
                run_dir = os.path.join(ROOT_DIR, "vault", "evals", "runs", metadata.run_id)
                os.makedirs(run_dir, exist_ok=True)
                with open(os.path.join(run_dir, "metadata.json"), "w") as f:
                    json.dump(metadata.to_dict(), f, indent=2)
                
                # Trigger Review Generation Fallback
                batch_summary = aggregate_batch(self.batch_id, self.inputs, [], [metadata.run_id])
                batch_summary.data["all_metadata"] = [metadata.to_dict()]
                
                packet_text = generate_review_packet(batch_summary, [], [])
                packet_path = save_review_packet(self.batch_id, packet_text)
                
                self.result.data = {
                    "batch_id": self.batch_id,
                    "target_agent": self.inputs.target_agent,
                    "verdict": "NO-SHIP",
                    "classification": "scenario_mismatch",
                    "error": mismatch_reason
                }
                self.result.artifacts = [packet_path]
                return self.result

            # ── 3. Validate scenario pack exists ─────────────────
            scenarios = load_scenario_pack(self.inputs.scenario_pack)
            if not scenarios:
                self._mark_error(f"Scenario pack '{self.inputs.scenario_pack}' not found or empty.")
                self.result.data = {"error_code": EvalError.SCENARIO_LOAD_FAILED}
                return self.result

            # ── 4. Standard Flow ─────────────────────────────────
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

            # Determine environment URL
            env_url = context.get("env_url", "https://x-agent.ai")  # Default to prod
            if self.inputs.environment == "local":
                env_url = context.get("local_url", "http://127.0.0.1:3000")
            elif getattr(self, "agent_conf", {}).get("demo_url"):
                env_url = self.agent_conf.get("demo_url")

            capture = None
            if self.inputs.browser_mode:
                if progress_callback: progress_callback("Initializing Live Browser", 5)
                capture = LiveBrowserCapture()
                connected = await capture.connect(self.inputs.target_agent, context)
                if not connected:
                    self._mark_error("Failed to connect to browser for live capture.")
                    self.result.data = {"error_code": EvalError.SESSION_LAUNCH_FAILED}
                    return self.result

            for i, scenario in enumerate(scenarios):
                run_id = f"{self.batch_id}_{i+1:02d}"
                run_ids.append(run_id)

                self.logger.info(
                    f"Run {i+1}/{len(scenarios)}: {scenario.get('title', 'unknown')} "
                    f"(mode: {'browser' if self.inputs.browser_mode else 'sim'})"
                )

                if self.inputs.browser_mode:
                    if progress_callback: progress_callback(f"Capturing Run {i+1}", 10 + (i * 10))
                    # Phase 5A: Live Browser Path
                    navigated = await capture.navigate_to_agent(env_url, self.inputs.target_agent)
                    if not navigated:
                        metadata = RunMetadata(
                            run_id=run_id, batch_id=self.batch_id,
                            target_agent=self.inputs.target_agent, environment=self.inputs.environment,
                            scenario_pack=self.inputs.scenario_pack, scenario_id=scenario.get("scenario_id"),
                            scenario_title=scenario.get("title"), difficulty=scenario.get("difficulty"),
                            max_turns=self.inputs.max_turns, status="error", error_code=EvalError.SESSION_LAUNCH_FAILED,
                            started_at=datetime.now().isoformat(), capture_source="live_browser"
                        )
                        transcript = []
                        scorecard = None
                    else:
                        metadata = RunMetadata(
                            run_id=run_id, batch_id=self.batch_id,
                            target_agent=self.inputs.target_agent, environment=self.inputs.environment,
                            scenario_pack=self.inputs.scenario_pack, scenario_id=scenario.get("scenario_id"),
                            scenario_title=scenario.get("title"), difficulty=scenario.get("difficulty"),
                            max_turns=self.inputs.max_turns, status="running", started_at=datetime.now().isoformat(),
                            capture_source="live_browser"
                        )
                        transcript = await capture.run_session(
                            scenario, self.inputs.max_turns, self.inputs.__dict__, run_id, self.batch_id
                        )
                        metadata.status = "success"
                        metadata.transcript_status = transcript[0].get("transcript_status", "failed") if transcript else "failed"
                        metadata.completion_reason = transcript[0].get("completion_reason") if transcript else None
                        metadata.actual_turns = len(transcript)
                        metadata.completed_at = datetime.now().isoformat()
                        
                        # Note: scoring still uses sim/Ollama logic on the captured transcript
                        scorecard = score_run(
                            run_id=run_id, target_agent=self.inputs.target_agent,
                            transcript=transcript, scenario=scenario,
                            rubric_name=self.inputs.scoring_rubric, pass_threshold=self.inputs.pass_threshold
                        )
                else:
                    if progress_callback: progress_callback(f"Simulating Run {i+1}", 10 + (i * 10))
                    # Phase 4 Path: Simulated
                    metadata, transcript, scorecard = await execute_simulated_run(
                        run_id=run_id,
                        batch_id=self.batch_id,
                        inputs=self.inputs,
                        scenario=scenario,
                        contract=self.contract
                    )

                # Save run artifacts
                # Log the effective contract in metadata for the run (always attach)
                metadata.eval_contract = self.contract.to_dict()
                
                if scorecard or transcript:
                    if scorecard:
                        metadata.classification = scorecard.classification
                    
                    artifacts = save_run_artifacts(
                        run_id=run_id,
                        batch_id=self.batch_id,
                        metadata=metadata,
                        transcript=transcript,
                        scorecard=scorecard if scorecard else Scorecard(run_id, scenario.get("scenario_id"), self.inputs.target_agent),
                    )
                    metadata.artifacts = artifacts
                    if scorecard:
                        scorecards.append(scorecard)

                all_metadata.append(metadata)

            if capture:
                await capture.close()

            # ── Phase 5C: APEX Reviewer Team ──────────────────
            reviewer_results = {}
            troy_patch = {}
            reviewer_status = "skipped"
            reviewer_error = None
            
            # Identify if at least one run is reviewable (has enough transcript turns)
            has_reviewable_data = any(m.is_reviewable for m in all_metadata)
            
            if has_reviewable_data and self.inputs.review_mode != "score_only":
                if progress_callback: progress_callback("Initializing APEX Reviewer Team", 30)
                self.logger.info("🛡️ Initiating APEX Reviewer Team...")
                
                reviewer_status = "pending"
                reviewer_error = None
                
                try:
                    runner = ReviewerRunner()
                    review_team = ReviewTeam(os.path.join(ROOT_DIR, "config", "review_team"), runner)
                    patch_gen = PromptPatchGenerator(os.path.join(ROOT_DIR, "config", "review_team"), runner)

                    # Collect session data for reviewers (V1: Use first run as representative)
                    representative_run = all_metadata[0]
                    transcript_path = os.path.join(ROOT_DIR, "vault", "evals", "runs", representative_run.run_id, "transcript.txt")
                    
                    transcript_text = "No transcript available."
                    if os.path.exists(transcript_path):
                        with open(transcript_path, "r", encoding="utf-8") as f:
                            transcript_text = f.read()
                    
                    session_data = {
                        "agent_name": self.inputs.target_agent,
                        "role_name": self.inputs.target_agent, 
                        "persona_description": "X-Agent Professional",
                        "scenario": representative_run.scenario_title,
                        "transcript_excerpt": transcript_text[:4000], 
                        "transcript_excerpt": transcript_text[:4000], 
                        "scorecard": scorecards[0].to_dict() if scorecards else {},
                        "failure_extract": "\n".join(scorecards[0].critical_failures) if (scorecards and scorecards[0].critical_failures) else "None",
                        "current_prompt": "UNAVAILABLE"
                    }

                    def on_step(name, percent):
                        if progress_callback: progress_callback(name, percent)

                    reviewer_results = review_team.run_full_review(session_data, on_step=on_step)
                    
                    if self.inputs.review_mode == "troy":
                        if progress_callback: progress_callback("Generating Troy Patch", 95)
                        troy_patch = patch_gen.generate_patch(session_data, reviewer_results)
                    
                    reviewer_status = "success"
                except Exception as rev_err:
                    reviewer_status = "error"
                    reviewer_error = str(rev_err)
                    self.logger.error(f"Reviewer Team failed: {rev_err}")
                
            if progress_callback: progress_callback("Finalizing Batch", 98)

            # Aggregate batch
            batch_summary = aggregate_batch(
                batch_id=self.batch_id,
                inputs=self.inputs,
                scorecards=scorecards,
                run_ids=run_ids,
            )
            
            # Attach metadata to summary data for fallback review rendering
            batch_summary.data["all_metadata"] = [m.to_dict() for m in all_metadata]
            batch_summary.data["reviewer_status"] = reviewer_status
            batch_summary.data["reviewer_error"] = reviewer_error
            batch_summary.data["reviewer_results"] = reviewer_results
            batch_summary.data["troy_patch"] = troy_patch

            # ── Generate Review Packet Artifact ──────────────────
            packet_text = generate_review_packet(batch_summary, scorecards, scenarios)
            packet_path = save_review_packet(self.batch_id, packet_text)
            
            # Sync explicit fields to top-level for Hub visibility
            batch_summary.reviewer_status = reviewer_status
            batch_summary.reviewer_error = reviewer_error
            batch_summary.review_artifact_path = packet_path
            batch_summary.review_packet_text = packet_text
            batch_summary.reviewer_results = reviewer_results
            batch_summary.troy_patch = troy_patch

            # Save batch artifacts
            batch_artifacts = save_batch_artifacts(self.batch_id, batch_summary)
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
                "capture_source": "live_browser" if self.inputs.browser_mode else "ollama_sim",
                "reviewer_results": reviewer_results,
                "troy_patch": troy_patch,
                "reviewer_status": reviewer_status,
                "reviewer_error": reviewer_error,
                "review_artifact_path": packet_path,
                "review_packet_text": packet_text
            }
            self.result.artifacts = batch_artifacts

            self._mark_success(
                f"Eval batch complete: {batch_summary.passed}/{len(scenarios)} passed "
                f"({batch_summary.pass_rate}%), verdict={batch_summary.verdict}"
            )

        except Exception as e:
            self.logger.error(f"Batch execution failed: {e}")
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
