import asyncio
import os
import sys
import logging
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# Set logging level to INFO
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("validation.sloane_refinement")

from tools.xagent_eval.tool import XAgentEvalTool

async def main():
    print("🚀 PHASE 5G: SLOANE REFINEMENT VALIDATION TEST")
    
    # Load gold prompt
    patched_prompt_path = os.path.join(ROOT_DIR, "patched_morgan_prompt.txt")
    with open(patched_prompt_path, "r", encoding="utf-8") as f:
        patched_prompt = f.read()
    
    tool = XAgentEvalTool()
    
    # Run a scenario where we expect agent to open first and scenario to complete early
    inputs = {
        "target_agent": "Morgan",
        "scenario_pack": "default_pack",
        "runs": 1,
        "difficulty": "medium",
        "browser_mode": True,
        "override_prompt": patched_prompt,
        "max_turns": 6,
        "pass_threshold": 80
    }
    
    context = {
        "env_url": "https://x-agent-website-dojo.vercel.app/"
    }
    
    if await tool.prepare(context, inputs):
        print("\n--- STARTING SESSION ---")
        result = await tool.execute(context)
        
        # Verify results
        score = result.data.get("average_score", 0)
        verdict = result.data.get("verdict", "UNKNOWN")
        passed = result.data.get("passed", 0)
        
        print(f"\n--- VALIDATION RESULTS ---")
        print(f"Score: {score}")
        print(f"Pass Count: {passed}")
        
        # Check metadata for evidence of refinements
        run_id = result.data.get("run_ids")[0] if result.data.get("run_ids") else None
        
        if run_id:
            meta_path = os.path.join(ROOT_DIR, "vault", "evals", "runs", run_id, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                    tx_status = meta.get('transcript_status')
                    cp_reason = meta.get('completion_reason')
                    print(f"Transcript Status: {tx_status}")
                    print(f"Completion Reason: {cp_reason}")
                    
                    # Success checks
                    if tx_status == "complete" and cp_reason in ("scenario_complete", "max_turns_reached"):
                        print("✅ SUCCESS: Refinements verified.")
                    else:
                        print(f"❌ FAILURE: Unexpected status/reason combination ({tx_status}/{cp_reason}).")
                    
                    # Verify first turn speaker
                    tx_path = os.path.join(ROOT_DIR, "vault", "evals", "runs", run_id, "transcript.json")
                    if os.path.exists(tx_path):
                        with open(tx_path, "r") as f:
                            tx = json.load(f)
                            # First non-system turn should be agent if it opened proactively
                            first_real_turn = next((t for t in tx if t['speaker'] != 'system'), None)
                            if first_real_turn:
                                print(f"First Real Turn Speaker: {first_real_turn['speaker']}")
                                if first_real_turn['speaker'] == 'agent_under_test':
                                    print("✅ SUCCESS: Agent-First startup confirmed.")
                                else:
                                    print("⚠️ WARNING: User spoke first (check agent proactive config).")
        
    else:
        print("❌ PREPARE FAILED")

if __name__ == "__main__":
    asyncio.run(main())
