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
    print("🚀 PHASE 5F: LIVE READINESS VERIFICATION (3 RERUNS)")
    
    # Load patched prompt
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
            "difficulty": "medium",
            "browser_mode": True, # LIVE WEBSITE
            "override_prompt": patched_prompt
        }
        
        context = {
            "env_url": "https://x-agent-website-dojo.vercel.app/"
        }
        
        if await tool.prepare(context, inputs):
            result = await tool.execute(context)
            results.append(result)
            
            # Extract data from the result
            # Based on BatchSummary schema: data["reviewer_results"]
            score = result.data.get("average_score", 0)
            
            # For transcript_status, we need to look into the individual run's metadata or turns
            # The tool returns BatchResult which has data = BatchSummary serialized
            status = "unknown"
            if result.data.get("run_ids"):
                run_id = result.data["run_ids"][0]
                # Try to find transcript_status in the reviewer summary or similar
                # Actually, transcript_capture.py sets turn["transcript_status"]
                # We can check if failed == 0
                status = "complete" if result.data.get("failed", 0) == 0 else "failed"

            print(f"Trial {i+1} Result: Score={score}, Status={status}")
        else:
            print(f"Trial {i+1} PREPARE FAILED")
            results.append(None)

    print("\n\n--- FINAL READINESS SUMMARY ---")
    for i, res in enumerate(results):
        if res:
            score = res.data.get("average_score", 0)
            status = "complete" if res.data.get("failed", 0) == 0 else "failed"
            print(f"Run {i+1}: Score={score}, Status={status}, Batch={res.data.get('batch_id')}")
        else:
            print(f"Run {i+1}: CRITICAL FAILURE")

if __name__ == "__main__":
    asyncio.run(main())
