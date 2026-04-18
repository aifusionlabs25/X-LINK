import subprocess
import time
import sys
import os

# Configuration
AGENTS = ["dani", "amy", "taylor", "morgan"]
SCENARIOS = 2 # Keeping it lean for the universal tune-up
TURNS = 8

def run_mel(agent):
    print(f"\n🚀 Starting Universal Tune-up for: {agent.upper()}")
    print(f"{'='*50}")
    
    cmd = [
        "python", "tools/mel_pilot.py",
        "--agent", agent,
        "--scenarios", str(SCENARIOS),
        "--turns", str(TURNS)
    ]
    
    try:
        # Start the process and stream output
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8',
            errors='replace'
        )
        
        for line in process.stdout:
            print(line, end='')
            
        process.wait()
        
        if process.returncode == 0:
            print(f"✅ Success: {agent} evolution complete.")
        else:
            print(f"❌ Error: {agent} evolution failed with code {process.returncode}.")
            
    except Exception as e:
        print(f"🔥 Critical Failure for {agent}: {e}")

def main():
    print(f"🏁 X-LINK UNIVERSAL FLEET TUNE-UP (GEMMA 4 BACKBONE)")
    print(f"Timestamp: {time.ctime()}")
    print(f"Target Fleet: {', '.join(AGENTS)}")
    print(f"{'='*50}\n")
    
    for agent in AGENTS:
        run_mel(agent)
        # Short cooldown between agents to allow VRAM/Ollama cleanup
        time.sleep(10)
        
    print("\n🎉 ALL AGENTS HAVE COMPLETED THE GEMMA 4 EVOLUTION LOOP.")
    print("Check the Hub or vault/mel/pending/ to approve the final patches.")

if __name__ == "__main__":
    main()
