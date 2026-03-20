
import os
import sys
import asyncio
import json

ROOT_DIR = r"c:\AI Fusion Labs\X AGENTS\REPOS\X-LINK"
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.tool import XAgentEvalTool

async def test_james():
    tool = XAgentEvalTool()
    tool.batch_id = "test_james_fit"
    
    inputs = {
        "target_agent": "james",
        "scenario_pack": "james_legal_intake",
        "environment": "local",
        "runs": 1,
        "turn_profile": "standard",
        "browser_mode": False,
        "review_mode": "full"
    }
    
    context = {
        "local_url": "http://127.0.0.1:3000",
        "env_url": "https://x-agent.ai"
    }
    
    print("🚀 Preparing James Role-Fit Run...")
    if await tool.prepare(context, inputs):
        print("✅ Preparation Successful.")
        print("🤖 Executing Simulation...")
        result = await tool.execute(context)
        print("🏁 Execution Complete.")
        print(f"Verdict: {result.data.get('verdict')}")
        print(f"Run IDs: {result.data.get('run_ids')}")
        
        # Save output for review
        with open("james_fit_result.json", "w") as f:
            json.dump(result.data, f, indent=2)
    else:
        print(f"❌ Preparation Failed: {tool.result.data}")

if __name__ == "__main__":
    asyncio.run(test_james())
