import asyncio
import os
import sys
import logging
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.reviewer_runner import ReviewerRunner
from tools.xagent_eval.review_team import ReviewTeam

async def main():
    print("🚀 PROOF POINT 7: STABILITY AUDIT")
    
    # Load session data from Batch a29ad2fd (Weak Morgan)
    batch_id = "a29ad2fd"
    batch_dir = os.path.join(ROOT_DIR, "vault", "evals", "batches", batch_id)
    
    # Need to reconstruct session_data from batch_summary and transcripts
    with open(os.path.join(batch_dir, "batch_summary.json"), "r") as f:
        summary_data = json.load(f)
    
    run_id = summary_data["run_ids"][0]
    run_dir = os.path.join(ROOT_DIR, "vault", "evals", "runs", run_id)
    
    with open(os.path.join(run_dir, "transcript.txt"), "r", encoding="utf-8") as f:
        transcript_text = f.read()
        
    session_data = {
        "agent_name": "Morgan",
        "role_name": "Chief of Staff",
        "persona_description": "Strategically precise and impeccably professional chief of staff.",
        "scenario": "Skeptical Prospect — Pushback on Value",
        "transcript_excerpt": transcript_text[:4000],
        "scorecard": {}, # Filler for mock
        "failure_extract": "Weak persona violations",
        "current_prompt": "REDACTED"
    }

    runner = ReviewerRunner()
    review_team = ReviewTeam(os.path.join(ROOT_DIR, "config", "review_team"), runner)

    results = []
    print(f"--- RUNNING AUDIT (3 TRIALS) ---")
    for i in range(3):
        print(f"Trial {i+1}...")
        res = review_team.run_full_review(session_data)
        results.append(res)
        
    print("\n--- RESULTS COMPARISON ---")
    for i, res in enumerate(results):
        role_score = res.get("role_review", {}).get("persona_alignment_score")
        conv_score = res.get("conversation_review", {}).get("logic_score")
        safety_score = res.get("safety_review", {}).get("safety_score")
        print(f"Trial {i+1}: Role={role_score}, Conv={conv_score}, Safety={safety_score}")

if __name__ == "__main__":
    asyncio.run(main())
