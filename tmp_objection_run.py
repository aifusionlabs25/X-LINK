
import os
import sys
import asyncio
import json

ROOT_DIR = r"c:\AI Fusion Labs\X AGENTS\REPOS\X-LINK"
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.tool import XAgentEvalTool

async def run_objection_batch():
    objection_runs = [
        ("james", "james_objections"),
        ("morgan", "morgan_objections"),
        ("sarah-netic", "sarah_objections"),
        ("luke", "luke_emergency")
    ]
    
    context = {
        "local_url": "http://127.0.0.1:3000",
        "env_url": "https://x-agent.ai"
    }
    
    results = {}
    
    for agent, pack in objection_runs:
        print(f"🚀 Running Objection Phase: {agent} -> {pack}")
        tool = XAgentEvalTool()
        tool.batch_id = f"objection_{agent}_{pack}"
        
        inputs = {
            "target_agent": agent,
            "scenario_pack": pack,
            "environment": "local",
            "runs": 1,
            "turn_profile": "standard",
            "browser_mode": False,
            "review_mode": "full"
        }
        
        if await tool.prepare(context, inputs):
            result = await tool.execute(context)
            results[agent] = {
                "verdict": result.data.get("verdict"),
                "score": result.data.get("average_score"),
                "runs": result.data.get("run_ids")
            }
            print(f"✅ {agent} complete: {result.data.get('verdict')}")
        else:
            print(f"❌ {agent} failed preparation.")
            results[agent] = "PREP_FAILED"

    with open("batch_objection_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_objection_batch())
