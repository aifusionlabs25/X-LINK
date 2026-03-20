import json
import os
import sys

def verify_results_payload():
    # Find the most recent batch
    batch_dir = "c:/AI Fusion Labs/X AGENTS/REPOS/X-LINK/vault/evals/batches"
    if not os.path.exists(batch_dir):
        print(f"Batch dir not found: {batch_dir}")
        return

    batches = sorted([d for d in os.listdir(batch_dir) if os.path.isdir(os.path.join(batch_dir, d))], reverse=True)
    if not batches:
        print("No batches found.")
        return

    latest_batch = batches[0]
    summary_path = os.path.join(batch_dir, latest_batch, "batch_summary.json")
    
    print(f"Verifying latest batch: {latest_batch}")
    
    if not os.path.exists(summary_path):
        print(f"Summary not found: {summary_path}")
        return

    with open(summary_path, "r") as f:
        data = json.load(f)

    # Check for new fields
    fields_to_check = [
        "reviewer_status",
        "reviewer_error",
        "review_artifact_path",
        "review_packet_text"
    ]

    missing = []
    for field in fields_to_check:
        if field not in data:
            missing.append(field)
    
    if missing:
        print(f"FAIL: Missing fields in batch_summary.json: {missing}")
    else:
        print("SUCCESS: All new status fields found in batch_summary.json")
        print(f"APEX Status: {data.get('reviewer_status')}")
        print(f"Review Packet Length: {len(data.get('review_packet_text', ''))} chars")

if __name__ == "__main__":
    verify_results_payload()
