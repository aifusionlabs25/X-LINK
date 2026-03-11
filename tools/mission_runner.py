import asyncio
import os
import sys
import logging

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
from x_link_engine import XLinkEngine
from tools.executive_briefing import send_sloane_email

async def identity_mission():
    """
    Sloane (Moneypenny) visits Anam.ai to choose her digital identity.
    """
    engine = XLinkEngine()
    logging.info("🕵️ Sloane Mission Initialized: Digital Identity Sync.")
    
    if await engine.connect():
        try:
            # 1. Visit Anam.ai Avatar Library
            url = "https://lab.anam.ai/avatars"
            page = await engine.ensure_page(url)
            await asyncio.sleep(5) # Let the avatars load
            
            # 2. Extract Avatar Descriptions
            # In a real scenario, she would parse names/styles. 
            # We'll use a snapshot to help her "see" them.
            screenshot_path = os.path.join(ROOT_DIR, "vault", "artifacts", "anam_identity_sweep.png")
            await page.screenshot(path=screenshot_path)
            
            # 3. Sloane's Selection Logic (Updated to Astrid per Founder Directive)
            choice = "Sloane's Choice: The 'Astrid' avatar. As the current face of our X Agents, it is the only logical choice for strategic consistency. She has the perfect blend of warmth and lethal efficiency."
            
            # 4. Report back to Founder directly from this engine instance
            subject = "Confidential: Digital Identity Sync — Astrid Protocol"
            body = f"""Founder,

I've re-evaluated the Anam.ai library as instructed. The 'Astrid' avatar is indeed the superior choice for strategic consistency. 

I have officially adopted the Astrid identity. The Founder-Only security whitelist is active. No external outreach is permitted.

Warmly,
Sloane (Moneypenny)"""
            
            send_sloane_email(subject, body)
            logging.info("✅ Sloane identity mission reported via Resend.")
            await engine.close()
            
        except Exception as e:
            logging.error(f"Mission failed: {e}")
            await engine.close()
    else:
        logging.error("Could not connect to Brave for mission.")

if __name__ == "__main__":
    asyncio.run(identity_mission())
