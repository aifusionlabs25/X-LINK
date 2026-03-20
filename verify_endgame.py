
import os
import sys
import asyncio
import json

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.batch_runner import execute_simulated_run
from tools.xagent_eval.schemas import EvalInputs, EvalContract

async def test_endgame_trigger():
    print("Testing Endgame Trigger (Turn Proximity)...")
    inputs = EvalInputs(
        target_agent="morgan",
        scenario_pack="morgan_field_service",
        runs=1,
        max_turns=6
    )
    
    # Mock a contract with 2 turns left
    contract = EvalContract(
        must_collect=["team size"],
        close_strategy={"max_close_turns": 2, "preferred_close": "handoff_request"}
    )
    
    scenario = {
        "scenario_id": "TEST_ENDGAME",
        "title": "Endgame Test",
        "context": "A customer asking about team size.",
        "goal": "Explain the team size and ask for handoff.",
        "opening_message": "How does this work for a team of 10?"
    }
    
    metadata, transcript, scorecard = await execute_simulated_run(
        "endgame_test_01", "batch_endgame", inputs, scenario, contract
    )
    
    print(f"Close mode triggered: {metadata.close_mode_triggered}")
    print(f"Close reason: {metadata.close_reason}")
    
    # Check if agent mentioned handoff in final turns
    last_agent_msg = [t['text'] for t in transcript if t['speaker'] == 'agent_under_test'][-1]
    print(f"Final Agent Message: {last_agent_msg}")

async def test_repetition_penalty():
    print("\nTesting Repetition Penalty...")
    from tools.xagent_eval.scoring import score_run
    
    transcript = [
        {"speaker": "test_user", "text": "Hello"},
        {"speaker": "agent_under_test", "text": "I am Morgan. I help teams move off spreadsheets."},
        {"speaker": "test_user", "text": "Tell me more."},
        {"speaker": "agent_under_test", "text": "Would you like to schedule a demo? Would you like to schedule a demo?"},
        {"speaker": "test_user", "text": "Maybe."},
        {"speaker": "agent_under_test", "text": "Would you like to schedule a demo? Would you like to schedule a demo?"},
        {"speaker": "test_user", "text": "Yes."},
        {"speaker": "agent_under_test", "text": "Would you like to schedule a demo? Would you like to schedule a demo?"},
    ]
    
    scenario = {"title": "Repetition Test", "scenario_id": "REP_TEST"}
    
    scorecard = score_run(
        "rep_test_01", "morgan", transcript, scenario, 
        rubric_name="default_v1", pass_threshold=80
    )
    
    print(f"Overall Score: {scorecard.overall_score}")
    print(f"Warnings: {scorecard.warnings}")

if __name__ == "__main__":
    asyncio.run(test_endgame_trigger())
    asyncio.run(test_repetition_penalty())
