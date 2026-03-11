"""
X-LINK HUB v3 — 10-Run Scripted Smoke Matrix
Runs the full smoke suite 10 times and aggregates pass/fail stats.
Run: python tests/smoke_matrix.py
"""

import subprocess
import sys
import os
import json
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

RUNS = 10
results = []

print("=" * 60)
print("X-LINK HUB v3 — 10-Run Smoke Matrix")
print(f"Started: {datetime.now().isoformat()}")
print("=" * 60)

for i in range(1, RUNS + 1):
    print(f"\n--- Run {i}/{RUNS} ---")
    proc = subprocess.run(
        [PYTHON, "-m", "pytest", "tests/test_hub_smoke.py", "-v", "--tb=short", "-q"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    # Parse results from output
    output = proc.stdout + proc.stderr
    passed = output.count(" PASSED")
    failed = output.count(" FAILED")
    errors = output.count(" ERROR")
    exit_code = proc.returncode
    
    run_result = {
        "run": i,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "exit_code": exit_code,
        "status": "GREEN" if exit_code == 0 else "RED",
    }
    results.append(run_result)
    
    status_icon = "✅" if exit_code == 0 else "❌"
    print(f"  {status_icon} Passed: {passed} | Failed: {failed} | Errors: {errors}")

# Summary
print("\n" + "=" * 60)
print("MATRIX SUMMARY")
print("=" * 60)

total_green = sum(1 for r in results if r["status"] == "GREEN")
total_red = sum(1 for r in results if r["status"] == "RED")

print(f"Total Runs:  {RUNS}")
print(f"Green:       {total_green}/{RUNS}")
print(f"Red:         {total_red}/{RUNS}")
print(f"Pass Rate:   {total_green/RUNS*100:.0f}%")
print(f"Verdict:     {'SHIP' if total_red == 0 else 'NO-SHIP'}")
print(f"Completed:   {datetime.now().isoformat()}")

# Save matrix report
report = {
    "test_suite": "test_hub_smoke.py",
    "total_runs": RUNS,
    "green": total_green,
    "red": total_red,
    "pass_rate": f"{total_green/RUNS*100:.0f}%",
    "verdict": "SHIP" if total_red == 0 else "NO-SHIP",
    "timestamp": datetime.now().isoformat(),
    "runs": results,
}

report_path = os.path.join(ROOT_DIR, "vault", "reports", "smoke_matrix_v3.json")
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print(f"\nReport saved: {report_path}")
