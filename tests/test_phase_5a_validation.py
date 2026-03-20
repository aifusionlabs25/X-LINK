"""
Phase 5A — Live Browser Validation
Runs one Morgan eval with browser_mode=True and verifies artifacts.
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.tool import XAgentEvalTool

async def main():
    tool = XAgentEvalTool()
    # Note: Using environment='local' just to signal preview/local intent,
    # but the LiveBrowserCapture defaults to https://x-agent.ai unless context specifies.
    result = await tool.run(
        context={
            "config_dir": os.path.join(ROOT_DIR, "config"),
            "vault_dir": os.path.join(ROOT_DIR, "vault"),
            "env_url": "https://x-agent-website-dojo.vercel.app/", # Dojo Preview URL
        },
        inputs={
            "target_agent": "Morgan",
            "scenario_pack": "default_pack",
            "runs": 1,
            "browser_mode": True,
            "max_turns": 3,
        }
    )

    print("="*60)
    print("PHASE 5A VALIDATION RESULTS")
    print("="*60)
    print(f"Status:      {result.status}")
    print(f"Source:      {result.data.get('capture_source')}")
    print(f"Batch ID:    {result.data.get('batch_id')}")
    
    if result.status == "success":
        run_id = result.data.get("run_ids")[0]
        # Check transcript status in metadata
        metadata_path = os.path.join(ROOT_DIR, "vault", "evals", "runs", run_id, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                import json
                meta = json.load(f)
                print(f"Trans Status: {meta.get('transcript_status')}")
                print(f"Prov Source:  {meta.get('capture_source')}")
                print(f"Prov Pack:    {meta.get('scenario_pack')}")
        
    if result.status == "error":
        print(f"Error Trace: {result.data.get('error', 'Unknown Error')}")
        
    print(f"Summary:     {result.summary}")
    print(f"Artifacts:   {len(result.artifacts)}")
    for a in result.artifacts:
        print(f"  {a}")

if __name__ == "__main__":
    asyncio.run(main())
