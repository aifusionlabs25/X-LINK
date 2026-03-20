import asyncio
import os
import sys
import logging
import json
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("rc_charter")

from tools.xagent_eval.tool import XAgentEvalTool

async def main():
    print("🏆 APEX PIPELINE: FINAL RC CERTIFICATION (10-SCRIPT BATCH)")
    print("---------------------------------------------------------")
    
    # Load gold prompt
    patched_prompt_path = os.path.join(ROOT_DIR, "patched_morgan_prompt.txt")
    with open(patched_prompt_path, "r", encoding="utf-8") as f:
        patched_prompt = f.read()
    
    tool = XAgentEvalTool()
    
    # Final 10-script batch on Gold Morgan
    inputs = {
        "target_agent": "Morgan",
        "scenario_pack": "default_pack",
        "runs": 10,
        "difficulty": "medium",
        "browser_mode": True,
        "override_prompt": patched_prompt,
        "max_turns": 10,
        "pass_threshold": 80
    }
    
    context = {
        "env_url": "https://x-agent-website-dojo.vercel.app/"
    }
    
    start_time = datetime.now()
    if await tool.prepare(context, inputs):
        result = await tool.execute(context)
        end_time = datetime.now()
        
        # Aggregate evidence
        data = result.data
        avg_score = data.get("average_score", 0)
        verdict = data.get("verdict", "UNKNOWN")
        passed = data.get("passed", 0)
        failed = data.get("failed", 0)
        total = passed + failed
        
        print("\n--- RC CERTIFICATION SUMMARY ---")
        print(f"Batch Verdict: {verdict}")
        print(f"Average Score: {avg_score}")
        print(f"Pass Rate: {passed}/{total}")
        print(f"Duration: {end_time - start_time}")
        
        # Success criteria for main merge
        if verdict == "SHIP" and avg_score >= 80 and failed == 0:
            print("\n✅ CERTIFIED FOR MAIN MERGE.")
        else:
            print("\n⚠️ RC FAILED TO MEET SHIP CRITERIA.")
            
    else:
        print("❌ PREPARE FAILED")

if __name__ == "__main__":
    asyncio.run(main())
