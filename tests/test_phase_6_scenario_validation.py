import asyncio
import os
import sys
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("phase_6_validation")

from tools.xagent_eval.tool import XAgentEvalTool

async def validate_pack(pack_name, runs=2):
    print(f"\n--- VALIDATING PACK: {pack_name} ---")
    
    # We create a fresh tool and browser session for each pack to ensure stability
    tool = XAgentEvalTool()
    
    inputs = {
        "target_agent": "Morgan",
        "scenario_pack": pack_name,
        "runs": runs,
        "difficulty": "mixed",
        "browser_mode": True,
        "max_turns": 8,
        "pass_threshold": 80
    }
    
    context = {
        "env_url": "https://x-agent-website-dojo.vercel.app/"
    }
    
    try:
        if await tool.prepare(context, inputs):
            result = await tool.execute(context)
            data = result.data
            print(f"Result for {pack_name}: {data.get('passed')}/{data.get('total_runs')} passed")
            print(f"Average Score: {data.get('average_score')}")
            print(f"Batch Verdict: {data.get('verdict')}")
            return result
        else:
            print(f"Failed to prepare {pack_name}")
            return None
    except Exception as e:
        print(f"Exception during validation of {pack_name}: {e}")
        return None

async def main():
    print("🚀 PHASE 6: SCENARIO PACK VALIDATION")
    print("====================================")
    
    # Validate Technical Support
    await validate_pack("technical_support", runs=2)
    
    # Validate Enterprise Sales
    await validate_pack("enterprise_sales", runs=2)

if __name__ == "__main__":
    asyncio.run(main())
