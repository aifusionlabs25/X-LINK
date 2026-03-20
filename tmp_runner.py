import subprocess
import json
import os
import sys

# Define parameters
params = {
    "agent": "dani",
    "pack": "enterprise_sales",
    "environment": "local",
    "type": "single",
    "difficulty": "mixed",
    "runs": 1,
    "turn_profile": 5,
    "review_mode": "deep",
    "browser_mode": False
}

# Ensure the correct python executable is used
python_exe = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")
if not os.path.exists(python_exe):
    python_exe = sys.executable

print(f"Launching eval with params: {params}")
# Run synchronously to capture output
result = subprocess.run([python_exe, "tools/run_eval.py", json.dumps(params)], capture_output=True, text=True)

print("--- STDOUT ---")
print(result.stdout)
print("--- STDERR ---")
print(result.stderr)
