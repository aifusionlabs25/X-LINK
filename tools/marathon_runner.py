import subprocess
import json
import os
import sys
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

script_path = os.path.join(ROOT_DIR, "tools", "run_eval.py")

# =====================================================================
# Parse arguments from Dojo API
# =====================================================================
if len(sys.argv) > 1:
    try:
        args = json.loads(sys.argv[1])
        MARATHON_AGENTS = args.get("agents", [])
        RUNS_PER_AGENT = int(args.get("runs", 1))
        DIFFICULTY = args.get("difficulty", "medium")
        ENV = args.get("environment", "local")
        REVIEW_MODE = args.get("review_mode", "score_only")
    except Exception as e:
        print(f"Error parsing marathon arguments: {e}")
        sys.exit(1)
else:
    print("No parameters provided.")
    sys.exit(1)
# =====================================================================

def run_marathon():
    agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
    with open(agents_path, 'r', encoding='utf-8') as f:
        agents_data = yaml.safe_load(f).get("agents", [])
    
    # Create lookup map
    agent_map = {a["slug"]: a for a in agents_data}

    for agent_slug in MARATHON_AGENTS:
        if agent_slug not in agent_map:
            print(f"⚠️ Skipping unknown agent: {agent_slug}")
            continue
            
        agent = agent_map[agent_slug]
        default_pack = agent.get("default_pack", f"{agent_slug}_pack")
        
        params = {
            "agent": agent_slug,
            "pack": default_pack,
            "environment": ENV,
            "type": "batch",
            "difficulty": DIFFICULTY,
            "runs": RUNS_PER_AGENT,
            "turn_profile": "standard",
            "review_mode": REVIEW_MODE, # Fast offline review
            "browser_mode": False        # Crucial for offline simulation
        }
        
        print(f"\n==========================================================")
        print(f"🚀 STARTING MARATHON RUN: {agent_slug.upper()} ({RUNS_PER_AGENT} runs)")
        print(f"==========================================================\n")
        
        # Use subprocess.run to wait for it to finish before moving to the next
        result = subprocess.run([PYTHON_EXE, script_path, json.dumps(params)])
        
        if result.returncode != 0:
            print(f"❌ Error during {agent_slug} marathon.")
        else:
            print(f"✅ Successfully completed marathon batch for {agent_slug}.")

if __name__ == "__main__":
    print("Initializing X-LINK Marathon Runner...")
    run_marathon()
    print("\n🏁 All marathon runs complete. Check the Hub Results tab.")
