import asyncio
import os
import sys
import logging
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# Set logging level to DEBUG to see the stability check logs
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("validation.turn_taking")

from tools.xagent_eval.tool import XAgentEvalTool

async def main():
    print("🚀 PHASE 5G: TURN-TAKING VALIDATION TEST")
    
    # Load gold prompt
    patched_prompt_path = os.path.join(ROOT_DIR, "patched_morgan_prompt.txt")
    with open(patched_prompt_path, "r", encoding="utf-8") as f:
        patched_prompt = f.read()
    
    tool = XAgentEvalTool()
    
    # Run a 2-turn scenario to verify completion gating
    inputs = {
        "target_agent": "Morgan",
        "scenario_pack": "default_pack",
        "runs": 1,
        "difficulty": "medium",
        "browser_mode": True,
        "override_prompt": patched_prompt,
        "max_turns": 2 # Small run for validation
    }
    
    context = {
        "env_url": "https://x-agent-website-dojo.vercel.app/"
    }
    
    if await tool.prepare(context, inputs):
        result = await tool.execute(context)
        
        # Verify results
        score = result.data.get("average_score", 0)
        verdict = result.data.get("verdict", "UNKNOWN")
        passed = result.data.get("passed", 0)
        
        print(f"\n--- VALIDATION RESULTS ---")
        print(f"Score: {score}")
        print(f"Pass Count: {passed}")
        print(f"Verdict: {verdict}")
        
        # Check logs/metadata for gating evidence
        batch_id = result.data.get("batch_id")
        run_id = result.data.get("run_ids")[0] if result.data.get("run_ids") else None
        
        if run_id:
            meta_path = os.path.join(ROOT_DIR, "vault", "evals", "runs", run_id, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                    print(f"Transcript Status: {meta.get('transcript_status')}")
                    if meta.get('transcript_status') == "complete":
                        print("✅ SUCCESS: Transcript marked COMPLETE.")
                    else:
                        print(f"❌ FAILURE: Transcript marked {meta.get('transcript_status')}.")
        
    else:
        print("❌ PREPARE FAILED")

if __name__ == "__main__":
    asyncio.run(main())
