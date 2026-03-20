
import os
import sys
import asyncio
import json

ROOT_DIR = r"c:\AI Fusion Labs\X AGENTS\REPOS\X-LINK"
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.tool import XAgentEvalTool

async def run_stress_batch():
    agents = ["james", "morgan", "sarah-netic", "dani", "amy", "luke", "claire"]
    pack = "global_stress_test"
    
    context = {
        "local_url": "http://127.0.0.1:3000",
        "env_url": "https://x-agent.ai"
    }
    
    results = {}
    
    for agent in agents:
        print(f"🔥 Running STRESS TEST: {agent} -> {pack}")
        tool = XAgentEvalTool()
        tool.batch_id = f"stress_{agent}_{pack}"
        
        inputs = {
            "target_agent": agent,
            "scenario_pack": pack,
            "environment": "local",
            "runs": 1,
            "turn_profile": "standard",
            "browser_mode": False,
            "review_mode": "full",
            "stress_test": True  # This flag overrides gating!
        }
        
        if await tool.prepare(context, inputs):
            result = await tool.execute(context)
            results[agent] = {
                "verdict": result.data.get("verdict"),
                "score": result.data.get("average_score"),
                "runs": result.data.get("run_ids")
            }
            print(f"🏁 {agent} stress complete: {result.data.get('verdict')}")
        else:
            print(f"❌ {agent} stress failed preparation.")
            results[agent] = "PREP_FAILED"

    with open("batch_stress_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_stress_batch())
