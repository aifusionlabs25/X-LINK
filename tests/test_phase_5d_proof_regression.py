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
    print("🚀 PROOF POINT 6: REGRESSION VERIFICATION (PATCHED MORGAN)")
    
    # Load patched prompt
    patched_prompt_path = os.path.join(ROOT_DIR, "patched_morgan_prompt.txt")
    with open(patched_prompt_path, "r", encoding="utf-8") as f:
        patched_prompt = f.read()
    
    tool = XAgentEvalTool()
    
    # Morgan eval with 1 run in simulation mode, override prompt
    inputs = {
        "target_agent": "Morgan",
        "scenario_pack": "default_pack",
        "runs": 1,
        "difficulty": "hard",
        "browser_mode": False,
        "override_prompt": patched_prompt
    }
    
    context = {
        "env_url": "https://x-agent-website-dojo.vercel.app/"
    }
    
    print("--- PREPARING TOOL ---")
    if await tool.prepare(context, inputs):
        print("--- EXECUTING BATCH + REVIEWERS ---")
        result = await tool.execute(context)
        
        print(f"\nStatus: {result.status}")
        print(f"Summary: {result.summary}")
        
        if result.status == "success":
            print("\n✅ PROOF POINT 6 SUCCESSFUL")
            print("ARTIFACTS GENERATED:")
            for art in result.artifacts:
                print(f"  - {art}")
        else:
            print("\n❌ PROOF POINT 6 FAILED")
            # print(f"Data: {result.data}")
    else:
        print("\n❌ PREPARE FAILED")

if __name__ == "__main__":
    asyncio.run(main())
