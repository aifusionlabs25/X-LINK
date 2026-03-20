import sys
import subprocess
import json

params = {
  "agent": "james",
  "pack": "default_pack",
  "environment": "local",
  "type": "single",
  "difficulty": "easy",
  "runs": 1,
  "turn_profile": "short",
  "review_mode": "score_only",
  "browser_mode": False
}

subprocess.run(["python", "tools/run_eval.py", json.dumps(params)])
