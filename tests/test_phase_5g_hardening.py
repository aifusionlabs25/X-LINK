import asyncio
import os
import sys
import logging
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from tools.xagent_eval.tool import XAgentEvalTool

async def main():
    print("🚀 PHASE 5G: FINAL HARDENING (3 RERUNS - TARGET >= 80)")
    
    # Load gold prompt
    patched_prompt_path = os.path.join(ROOT_DIR, "patched_morgan_prompt.txt")
    with open(patched_prompt_path, "r", encoding="utf-8") as f:
        patched_prompt = f.read()
    
    tool = XAgentEvalTool()
    
    results = []
    
    for i in range(3):
        print(f"\n--- TRIAL {i+1} START ---")
        # Morgan eval with 1 run in BROWSER mode, override prompt
        inputs = {
            "target_agent": "Morgan",
            "scenario_pack": "default_pack",
            "runs": 1,
            "difficulty": "hard", # Hardening on 'hard'
            "browser_mode": True,
            "override_prompt": patched_prompt
        }
        
        context = {
            "env_url": "https://x-agent-website-dojo.vercel.app/"
        }
        
        if await tool.prepare(context, inputs):
            result = await tool.execute(context)
            results.append(result)
            
            score = result.data.get("average_score", 0)
            status = "complete" if result.data.get("failed", 0) == 0 else "failed"
            
            print(f"Trial {i+1} Result: Score={score}, Status={status}")
            
            if score < 80:
                print(f"⚠️ WARNING: Score {score} is below target 80.")
            if status != "complete":
                print(f"❌ ERROR: Transcript status is {status}.")
        else:
            print(f"Trial {i+1} PREPARE FAILED")
            results.append(None)

    print("\n\n--- HARDENING SUMMARY ---")
    all_pass = True
    for i, res in enumerate(results):
        if res:
            score = res.data.get("average_score", 0)
            status = "complete" if res.data.get("failed", 0) == 0 else "failed"
            print(f"Run {i+1}: Score={score}, Status={status}, Batch={res.data.get('batch_id')}")
            if score < 80 or status != "complete":
                all_pass = False
        else:
            print(f"Run {i+1}: CRITICAL FAILURE")
            all_pass = False
            
    if all_pass:
        print("\n✅ ALL 3 TRIALS PASSED HARDENING CRITERIA (>=80, complete)")
    else:
        print("\n❌ HARDENING CRITERIA NOT MET")

if __name__ == "__main__":
    asyncio.run(main())
