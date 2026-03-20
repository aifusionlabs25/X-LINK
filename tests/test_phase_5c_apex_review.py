import asyncio
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from tools.xagent_eval.tool import XAgentEvalTool

async def main():
    print("🚀 TARGETING PHASE 5C: APEX REVIEWER TEAM VALIDATION")
    
    tool = XAgentEvalTool()
    
    # Morgan eval with 1 run in simulation mode to speed up validation
    inputs = {
        "target_agent": "Morgan",
        "scenario_pack": "default_pack",
        "runs": 1,
        "difficulty": "mixed",
        "browser_mode": False 
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
            print("\n✅ VALIDATION SUCCESSFUL")
            print("ARTIFACTS GENERATED:")
            for art in result.artifacts:
                print(f"  - {art}")
                
            # Check if troy patch exists in data
            if "troy_patch" in result.data:
                print("\n🔥 TROY PATCH CANDIDATE FOUND:")
                print(json.dumps(result.data["troy_patch"], indent=2))
        else:
            print("\n❌ VALIDATION FAILED")
            print(f"Data: {result.data}")
    else:
        print("\n❌ PREPARE FAILED")

if __name__ == "__main__":
    import json
    asyncio.run(main())
