import os
import json
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import BatchSummary, Scorecard
from tools.xagent_eval.review_packet import generate_review_packet, save_review_packet

def main():
    batch_id = "381464a2"
    batch_dir = f"vault/evals/batches/{batch_id}"
    
    with open(f"{batch_dir}/batch_summary.json", "r") as f:
        data = json.load(f)
        
    summary = BatchSummary(
        batch_id=data["batch_id"],
        target_agent=data["target_agent"],
        environment=data["environment"],
        scenario_pack=data["scenario_pack"]
    )
    summary.data = data.get("data", {})
    summary.passed = data["passed"]
    summary.failed = data["failed"]
    summary.pass_rate = data["pass_rate"]
    summary.average_score = data["average_score"]
    summary.category_averages = data["category_averages"]
    
    print("--- GENERATING PACKET ---")
    try:
        packet_text = generate_review_packet(summary, [], [])
        print("PACKET TEXT GENERATED")
        print(packet_text[:500])
        
        path = save_review_packet(batch_id, packet_text)
        print(f"PACKET SAVED TO: {path}")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
