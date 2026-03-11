"""
XLINK HEARTBEAT — The Autonomous Heart of the Command Center
============================================================
Orchestrates the 6:00 AM "Morning Newspaper" routine.
- 05:45: Executive Briefing Generation
- 06:00: Usage Audit & Dashboard Refresh
- Post-Audit: Focus & Bring Command Center to Front
"""

import schedule
import time
import subprocess
import os
import sys
import asyncio
from datetime import datetime

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = os.path.join(ROOT_DIR, '.venv', 'Scripts', 'python.exe')
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable  # Fallback to current python if venv not found

sys.path.insert(0, ROOT_DIR)
from x_link_engine import XLinkEngine

def run_script(script_name):
    """Utility to run a python script in the tools directory."""
    script_path = os.path.join(ROOT_DIR, 'tools', script_name)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Triggering {script_name}...")
    try:
        subprocess.run([PYTHON_EXE, script_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running {script_name}: {e}")

async def focus_command_center():
    """Brings the audit_hub.html to the front of the browser or launches Brave if needed."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Focusing Executive Command Center...")
    engine = XLinkEngine()
    hub_path = os.path.join(ROOT_DIR, 'audit_hub.html')
    hub_url = f"file:///{hub_path.replace(os.sep, '/')}"

    if await engine.connect():
        # ensure_page handles finding the tab or opening it
        page = await engine.ensure_page(hub_url)
        await page.bring_to_front()
        print("✅ Dashboard focused and active.")
        await engine.close()
    else:
        print("⚠️ Brave connection not found. Attempting to launch Brave...")
        # Path to Brave - typical installation path
        brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        if os.path.exists(brave_path):
            subprocess.Popen([brave_path, "--remote-debugging-port=9222", hub_url])
            print("🚀 Brave launched with Executive Hub.")
        else:
            print("❌ Brave executable not found at C:\\Program Files...")

def daily_routine():
    """The full 6:00 AM routine."""
    print(f"\n{'='*60}")
    print(f"  🔆 STARTING MORNING ROUTINE: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*60}\n")
    
    # 1. Generate Briefing
    run_script('executive_briefing.py')
    
    # 2. Run Audit (this also triggers dashboard_gen.py)
    run_script('usage_auditor.py')
    
    # 3. Focus Dashboard
    asyncio.run(focus_command_center())
    
    print(f"\n{'='*60}")
    print(f"  🗞️ MORNING NEWSPAPER READY AT {datetime.now().strftime('%H:%M')}")
    print(f"{'='*60}\n")

# ── Scheduler Configuration ──────────────────────────────────────────

# 02:00 AM - Midnight Scout (Intelligence Gathering)
schedule.every().day.at("02:00").do(lambda: run_script('intelligence_sweeper.py'))

# 03:00 AM - Discord Presence Check
schedule.every().day.at("03:00").do(lambda: run_script('discord_watcher.py'))

# 05:45 AM - Strategic Briefing
schedule.every().day.at("05:45").do(lambda: run_script('executive_briefing.py'))

# 06:00 AM - Full Audit & Delivery
schedule.every().day.at("06:00").do(daily_routine)

# ── Heartbeat Loop ───────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"{'='*60}")
    print(f"  ❤️ XLINK HEARTBEAT ACTIVE")
    print(f"  🕒 Current Time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"  📅 Scheduled: 05:45 (Briefing), 06:00 (Audit & Focus)")
    print(f"{'='*60}")
    
    # Optional: Run once on startup for debug/verification
    # daily_routine()

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n👋 Heartbeat stopped by user.")
