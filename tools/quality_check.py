import asyncio
import os
import sys
import yaml
import json
import logging
import requests
from datetime import datetime, timedelta

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("quality_check")

class SystemHeartbeat:
    def __init__(self):
        self.results = []

    def log(self, icon, message):
        logger.info(f"{icon} {message}")
        self.results.append({"icon": icon, "message": message})

    async def check_browser(self):
        engine = XLinkEngine()
        if await engine.connect():
            self.log("✅", "Browser Connected (CDP 9222 active)")
            pages = engine.context.pages
            self.log("📄", f"Active Tabs: {len(pages)}")
            await engine.close()
            return True
        else:
            self.log("❌", "Browser Disconnected (Port 9222 target not found)")
            return False

    def check_mappings(self):
        path = os.path.join(ROOT_DIR, "config", "agents.yaml")
        if not os.path.exists(path):
            self.log("❌", "agents.yaml missing")
            return
        
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        agents = config.get("agents", [])
        self.log("🤖", f"Found {len(agents)} agents in configuration")
        
        missing_anam = [a['name'] for a in agents if not a.get("anam_name")]
        if missing_anam:
            self.log("⚠️", f"Missing anam_name for: {', '.join(missing_anam)}")
        else:
            self.log("✅", "All agents have valid Anam mappings")

        # Check sync freshness
        now = datetime.now()
        stale = []
        for a in agents:
            ls = a.get("last_synced")
            if not ls:
                stale.append(a['name'])
            else:
                try:
                    dt = datetime.fromisoformat(ls)
                    if now - dt > timedelta(days=2):
                        stale.append(a['name'])
                except:
                    stale.append(a['name'])
        
        if stale:
            self.log("⏳", f"Sync required for: {', '.join(stale)}")
        else:
            self.log("✅", "All agents recently synced")

    def check_hub_api(self):
        hub_url = "http://localhost:5001/api/data"
        try:
            resp = requests.get(hub_url, timeout=3)
            if resp.status_code == 200:
                self.log("✅", f"Hub API Online (Port 5001)")
            else:
                self.log("⚠️", f"Hub API returned status {resp.status_code}")
        except:
            self.log("❌", "Hub API Offline (Is Synapse Bridge running?)")

    async def run_full_audit(self):
        logger.info("\n" + "="*40)
        logger.info("🛡️  X-LINK SYSTEM HEARTBEAT AUDIT")
        logger.info("="*40 + "\n")
        
        await self.check_browser()
        self.check_mappings()
        self.check_hub_api()
        
        logger.info("\n" + "="*40)
        logger.info("✨ AUDIT COMPLETE")
        logger.info("="*40 + "\n")

if __name__ == "__main__":
    heartbeat = SystemHeartbeat()
    asyncio.run(heartbeat.run_full_audit())
