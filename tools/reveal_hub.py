import asyncio
import os
import sys

# Add root to path for x_link_engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from x_link_engine import XLinkEngine

async def reveal():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hub_path = os.path.join(root_dir, 'audit_hub.html')
    hub_url = f"file:///{hub_path.replace(os.sep, '/')}"
    
    print(f"🔗 Targeted Hub: {hub_url}")
    
    engine = XLinkEngine()
    if await engine.connect():
        # ensure_page will find the tab if open, or open a new one
        page = await engine.ensure_page(hub_url)
        await page.bring_to_front()
        print("✅ Executive Hub has been loaded and focused in your current Brave session.")
        await engine.close()
    else:
        print("❌ Could not connect to the current Brave session. Please ensure Brave is running with --remote-debugging-port=9222.")

if __name__ == "__main__":
    asyncio.run(reveal())
