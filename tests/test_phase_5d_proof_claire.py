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
    print("🚀 PROOF POINT 1: CLAIRE (TECHNICAL SUPPORT) EVALUATION")
    
    tool = XAgentEvalTool()
    
    # Claire eval with 1 run in simulation mode
    inputs = {
        "target_agent": "Claire",
        "scenario_pack": "technical_support",
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
            print("\n✅ PROOF POINT 1 SUCCESSFUL")
            print("ARTIFACTS GENERATED:")
            for art in result.artifacts:
                print(f"  - {art}")
        else:
            print("\n❌ PROOF POINT 1 FAILED")
            print(f"Data: {result.data}")
    else:
        print("\n❌ PREPARE FAILED")

if __name__ == "__main__":
    asyncio.run(main())
