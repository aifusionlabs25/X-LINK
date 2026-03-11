import asyncio
import os
import sys
import logging

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
from x_link_engine import XLinkEngine

# Configuration: Define the "Active Core Set"
CORE_SET = [
    "file:///" + os.path.join(ROOT_DIR, "audit_hub.html").replace("\\", "/"),
    "https://mail.google.com/mail/u/2/#inbox",
    "https://calendar.google.com/calendar/u/1/r/day"
]

async def bootstrap():
    """
    Ensures the X-Link Hub starts with a clean, optimized tab set.
    """
    engine = XLinkEngine()
    logging.info("🚀 Bootstrapping X-Link Core Set...")
    
    if await engine.connect():
        try:
            # 1. Purge Bloat
            # We pass the core set fragment to cleanup_tabs to ensure we don't close what we're about to open
            await engine.cleanup_tabs(keep_list=["audit_hub.html", "mail.google.com", "calendar.google.com"])
            
            # 2. Warm Start Core Tabs
            for url in CORE_SET:
                logging.info(f"Checking core tab: {url}")
                await engine.ensure_page(url)
                await asyncio.sleep(1) # Interval to prevent overlap
                
            logging.info("✅ Hub Bootstrap Complete. Brave is optimized.")
            await engine.close()
        except Exception as e:
            logging.error(f"Bootstrap failed: {e}")
            await engine.close()
    else:
        logging.error("Could not connect to Brave for bootstrap.")

if __name__ == "__main__":
    asyncio.run(bootstrap())
