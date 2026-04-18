from __future__ import annotations

import os
import sys
import uuid
from typing import Dict, Any, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import EvalInputs
from tools.xagent_eval.batch_runner import aggregate_batch, save_run_artifacts, save_batch_artifacts
from tools.xagent_eval.scenario_bank import select_scenarios
from tools.mel_pilot import (
    emit_progress,
    reset_progress,
    register_session,
    cleanup_session,
    preflight_check,
    load_agent_config,
    snapshot_persona,
    extract_diagnostic,
    generate_challengers,
    save_pending,
)
from .dani_audit import apply_dani_audit
from .sim_runner import execute_simulated_run_v2
from .validators import run_deterministic_checks


async def evaluate_prompt_v2(
    agent_slug: str,
    prompt_text: str,
    scenario_pack: str,
    scenarios: List[Dict[str, Any]],
    max_turns: int,
    stage_name: str = "eval_v2",
    base_pct: int = 0,
    seed: int = 7,
) -> Dict[str, Any]:
    inputs = EvalInputs(
        target_agent=agent_slug,
        environment="sim_v2",
        scenario_pack=scenario_pack,
        runs=len(scenarios),
        browser_mode=False,
        save_screenshots=False,
        override_prompt=prompt_text,
        max_turns=max_turns,
        limitless=False,
        transcript_mode="mel_v2_sim",
        seed=seed,
    )
    if not scenarios:
        return {"error": "No scenarios found", "score": 0, "pass_rate": 0}

    batch_id = f"melv2_{uuid.uuid4().hex[:8]}"
    scorecards = []
    run_ids = []

    for i, scenario in enumerate(scenarios):
        run_id = f"melv2_run_{uuid.uuid4().hex[:8]}"
        run_ids.append(run_id)
        progress_pct = base_pct + int((i / max(1, len(scenarios))) * 10)

        def on_turn_cb(turn_num, user_msg, agent_reply):
            turn_pct = progress_pct + min(
                10,
                int((turn_num / max(1, max_turns)) * max(1, int(10 / max(1, len(scenarios))))),
            )
            emit_progress(
                stage_name,
                "active",
                f"Scenario {i+1}: Turn {turn_num}",
                turn_pct,
                agent_slug,
                {
                    "turn": turn_num,
                    "scenario": i + 1,
                    "user": user_msg,
                    "agent_msg": agent_reply,
                    "engine": "mel_v2",
                },
            )

        metadata, transcript, scorecard, contract = await execute_simulated_run_v2(
            run_id=run_id,
            batch_id=batch_id,
            inputs=inputs,
            scenario=scenario,
            on_turn=on_turn_cb,
        )

        if scorecard:
            checks = run_deterministic_checks(transcript, contract, scenario)
            scorecard.warnings.extend(
                finding for finding in checks["warnings"] if finding not in scorecard.warnings
            )
            scorecard.critical_failures.extend(
                finding for finding in checks["critical_failures"] if finding not in scorecard.critical_failures
            )
            scorecard.harness_artifacts.extend(
                finding for finding in checks["harness_artifacts"] if finding not in scorecard.harness_artifacts
            )
            if agent_slug == "dani":
                scorecard = apply_dani_audit(scorecard, transcript)
            save_run_artifacts(run_id, batch_id, metadata, transcript, scorecard)
            scorecards.append(scorecard)

    summary = aggregate_batch(batch_id, inputs, scorecards, run_ids)
    summary.data["engine"] = "mel_v2"
    save_batch_artifacts(batch_id, summary)

    return {
        "batch_id": batch_id,
        "score": summary.average_score,
        "pass_rate": summary.pass_rate,
        "verdict": summary.verdict,
        "category_averages": summary.category_averages,
        "top_failure_categories": summary.top_failure_categories,
        "total_runs": summary.total_runs,
        "passed": summary.passed,
        "failed": summary.failed,
        "engine": "mel_v2",
    }


async def run_evolution_v2(
    agent_slug: str,
    scenario_pack: str = "default_pack",
    num_scenarios: int = 3,
    max_turns: int = 8,
    difficulty: str = "mixed",
    seed: int = 7,
) -> Dict[str, Any]:
    reset_progress()
    register_session()

    try:
        emit_progress("preflight", "active", "Checking Ollama connection...", 5, agent_slug, {"engine": "mel_v2"})
        if not preflight_check():
            emit_progress("preflight", "error", "Ollama is not running. Aborting.", 5, agent_slug, {"engine": "mel_v2"})
            return {"error": "Ollama is not running. Aborting.", "engine": "mel_v2"}
        emit_progress("preflight", "done", "Ollama is online.", 10, agent_slug, {"engine": "mel_v2"})

        emit_progress("load_agent", "active", f"Loading agent config for '{agent_slug}'...", 12, agent_slug, {"engine": "mel_v2"})
        agent_config = load_agent_config(agent_slug)
        current_persona = agent_config.get("persona", "")
        emit_progress(
            "load_agent",
            "done",
            f"Loaded '{agent_config.get('name', agent_slug)}' persona. Pack: {scenario_pack}",
            15,
            agent_slug,
            {"engine": "mel_v2"},
        )

        emit_progress("snapshot", "active", "Snapshotting for rollback...", 18, agent_slug, {"engine": "mel_v2"})
        snapshot_path = snapshot_persona(agent_slug, current_persona)
        emit_progress("snapshot", "done", "Persona snapshot saved.", 20, agent_slug, {"engine": "mel_v2"})

        if scenario_pack == "default_pack":
            auto_pack = f"{agent_slug}_platform_sales"
            candidate = os.path.join(ROOT_DIR, "config", "eval_scenarios", f"{auto_pack}.yaml")
            if os.path.exists(candidate):
                scenario_pack = auto_pack

        emit_progress("baseline", "active", f"Selecting {num_scenarios} scenarios from '{scenario_pack}'...", 22, agent_slug, {"engine": "mel_v2"})
        scenarios = select_scenarios(pack_name=scenario_pack, difficulty=difficulty, count=num_scenarios, seed=seed)
        if not scenarios:
            emit_progress("baseline", "error", "No scenarios were found to test against.", 22, agent_slug, {"engine": "mel_v2"})
            return {"error": "No scenarios were found to test against.", "engine": "mel_v2"}

        baseline_result = await evaluate_prompt_v2(
            agent_slug=agent_slug,
            prompt_text=current_persona,
            scenario_pack=scenario_pack,
            scenarios=scenarios,
            max_turns=max_turns,
            stage_name="baseline",
            base_pct=25,
            seed=seed,
        )
        emit_progress(
            "baseline",
            "done",
            f"Baseline: Score={baseline_result.get('score')}%, Pass Rate={baseline_result.get('pass_rate')}%",
            35,
            agent_slug,
            {"score": baseline_result.get("score"), "pass_rate": baseline_result.get("pass_rate"), "engine": "mel_v2"},
        )

        emit_progress("diagnose", "active", "Analyzing baseline performance...", 40, agent_slug, {"engine": "mel_v2"})
        diagnostic = extract_diagnostic(agent_slug, batch_data=baseline_result)
        emit_progress(
            "diagnose",
            "done",
            f"Weakest: {diagnostic['failure_category']} ({diagnostic['failure_rate']}% failure rate)",
            45,
            agent_slug,
            {"failure_category": diagnostic["failure_category"], "failure_rate": diagnostic["failure_rate"], "engine": "mel_v2"},
        )

        emit_progress("troy", "active", "Generating challenger prompt patches...", 50, agent_slug, {"engine": "mel_v2"})
        challengers = generate_challengers(agent_config, diagnostic)
        if not challengers:
            emit_progress("troy", "error", "Prompt challenger generation failed.", 50, agent_slug, {"engine": "mel_v2"})
            return {"error": "Troy failed to generate challenger prompts.", "diagnostic": diagnostic, "engine": "mel_v2"}
        emit_progress("troy", "done", f"Generated {len(challengers)} challengers.", 60, agent_slug, {"engine": "mel_v2"})

        challenger_results = []
        for index, challenger in enumerate(challengers):
            base_stage_pct = 65 + (index * 15)
            result = await evaluate_prompt_v2(
                agent_slug=agent_slug,
                prompt_text=challenger["prompt"],
                scenario_pack=scenario_pack,
                scenarios=scenarios,
                max_turns=max_turns,
                stage_name=f"challenger_{index+1}",
                base_pct=base_stage_pct,
                seed=seed,
            )
            challenger_results.append(result)
            emit_progress(
                f"challenger_{index+1}",
                "done",
                f"Challenger {index+1} ({challenger['variant']}): Score={result.get('score')}%, Pass Rate={result.get('pass_rate')}%",
                base_stage_pct + 10,
                agent_slug,
                {
                    "variant": challenger["variant"],
                    "score": result.get("score"),
                    "pass_rate": result.get("pass_rate"),
                    "engine": "mel_v2",
                },
            )

        emit_progress("saving", "active", "Saving results for approval...", 92, agent_slug, {"engine": "mel_v2"})
        pending_id = save_pending(
            agent_slug=agent_slug,
            diagnostic=diagnostic,
            baseline_result=baseline_result,
            challengers=challengers,
            challenger_results=challenger_results,
            snapshot_path=snapshot_path,
        )

        best_challenger = max(challenger_results, key=lambda item: item.get("score", 0))
        improvement = round(best_challenger.get("score", 0) - baseline_result.get("score", 0), 1)
        emit_progress(
            "complete",
            "done",
            f"Complete! Baseline: {baseline_result.get('score', 0)}% to Best: {best_challenger.get('score', 0)}% ({'+' if improvement > 0 else ''}{improvement}%). Awaiting approval.",
            100,
            agent_slug,
            {
                "baseline_score": baseline_result.get("score", 0),
                "best_score": best_challenger.get("score", 0),
                "improvement": improvement,
                "pending_id": pending_id,
                "engine": "mel_v2",
            },
        )
        return {
            "status": "complete",
            "pending_id": pending_id,
            "agent": agent_slug,
            "baseline_score": baseline_result.get("score", 0),
            "best_challenger_score": best_challenger.get("score", 0),
            "improvement": improvement,
            "recommendation": "APPROVE" if improvement >= 10 else "REVIEW",
            "diagnostic": diagnostic,
            "awaiting_approval": True,
            "engine": "mel_v2",
        }
    finally:
        cleanup_session()
