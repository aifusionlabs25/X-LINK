import asyncio
import logging
import os
import sys
import re
import json
import requests
from datetime import datetime
from playwright.async_api import Page

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine
from tools.executive_briefing import send_sloane_email

# Configuration
POLL_INTERVAL = 300  # 5 minutes
AUTHORIZED_SENDERS = ["aifusionlabs@gmail.com", "rvicks@gmail.com", "novaaifusionlabs@gmail.com"]
BRIDGE_URL = "http://127.0.0.1:5001"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class EmailCommander:
    def __init__(self):
        self.engine = XLinkEngine()
        self.last_checked_id = None

    async def classify_command(self, sender, subject, body):
        """Uses Ollama to determine if an email is a command."""
        prompt = f"""
        You are Sloane's Command Processor. Analyze the following email from '{sender}'.
        Subject: {subject}
        Body: {body}

        Determine if this is a command to trigger a tool. 
        Available Tools:
        - 'audit': Usage extraction, cost audits, or checking balance.
        - 'sync': Full engine sync, updating metrics, or universal sync.
        - 'scout': Scouting intelligence, checking Keep.md, or autoresearch.
        - 'briefing': Asking for a report, status update, or briefing.

        Return ONLY a JSON object: {{"is_command": true/false, "tool": "tool_name", "reason": "brief reason"}}.
        If not a command, "tool" should be null.
        """
        
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": "qwen3-coder-next",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=20)
            result = response.json()
            return json.loads(result['response'])
        except Exception as e:
            logging.error(f"Classification error: {e}")
            # Fallback to simple keyword check if Ollama fails
            text = (subject + " " + body).lower()
            if "audit" in text: return {"is_command": True, "tool": "audit"}
            if "sync" in text: return {"is_command": True, "tool": "sync"}
            if "scout" in text: return {"is_command": True, "tool": "scout"}
            if "briefing" in text: return {"is_command": True, "tool": "briefing"}
            return {"is_command": False, "tool": None}

    async def poll_gmail(self):
        logging.info("🕵️‍♀️ Sloane is checking her correspondence...")
        if not await self.engine.connect():
            return

        try:
            page = await self.engine.ensure_page("https://mail.google.com/mail/u/novaaifusionlabs@gmail.com/#inbox", wait_sec=5, account_email="novaaifusionlabs@gmail.com")
            
            # Look for unread emails
            # This is a simplified selector for Gmail unread rows
            unread_rows = await page.locator('tr.zE').all()
            logging.info(f"📬 Found {len(unread_rows)} unread emails.")

            for row in unread_rows:
                try:
                    # Extract sender and subject
                    sender_el = row.locator('span.bA4 span').first
                    sender_text = await sender_el.get_attribute('email') or await sender_el.inner_text()
                    
                    subject_el = row.locator('span.bog span').first
                    subject_text = await subject_el.inner_text()

                    logging.info(f"📧 Reviewing email from: {sender_text} | Sub: {subject_text}")

                    # 1. Authorization Check
                    is_authorized = any(authorized in sender_text.lower() for authorized in AUTHORIZED_SENDERS)
                    
                    if not is_authorized:
                        logging.info(f"⏭️ Skipping unauthorized sender: {sender_text}")
                        # Mark as read or skip
                        continue

                    # 2. Extract Body (Click to open, read, then back)
                    await row.click()
                    await asyncio.sleep(2)
                    body_el = page.locator('div.a3s.aiL').first
                    body_text = await body_el.inner_text()
                    
                    # 3. Process via Sloane's Core Brain (Synapse Bridge)
                    try:
                        logging.info(f"🧠 Forwarding directive to Sloane's Core Brain...")
                        chat_resp = requests.post(
                            f"{BRIDGE_URL}/api/chat", 
                            json={"message": f"INCOMING CEO DIRECTIVE via Email ({sender_text}):\n\n{body_text}"},
                            timeout=60
                        )
                        if chat_resp.status_code == 200:
                            reply = chat_resp.json().get("reply", "Directive processed.")
                            logging.info(f"✅ Sloane Response: {reply}")
                            
                            # Reply via Gmail UI (gsuite_handler)
                            reply_to = sender_text if "@" in sender_text else "aifusionlabs@gmail.com"
                            try:
                                import subprocess
                                PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
                                subprocess.Popen([
                                    PYTHON_EXE,
                                    os.path.join(ROOT_DIR, "tools", "gsuite_handler.py"),
                                    "--action", "gmail_send",
                                    "--to", reply_to,
                                    "--subject", f"Re: {subject_text}",
                                    "--body", f"{reply}\n\n— Sloane"
                                ])
                                logging.info(f"📧 Reply dispatched via Gmail to {reply_to}")
                            except Exception as reply_err:
                                logging.error(f"Reply dispatch failed: {reply_err}")
                    except Exception as brain_err:
                        logging.error(f"Brain forwarding failed: {brain_err}")
                    
                    # Go back to inbox
                    await page.locator('div[aria-label="Back to Inbox"]').first.click()
                    await asyncio.sleep(1)

                except Exception as row_err:
                    logging.error(f"Error processing row: {row_err}")
                    await page.goto("https://mail.google.com/mail/u/novaaifusionlabs@gmail.com/#inbox") # Reset
                    await asyncio.sleep(3)

        except Exception as e:
            logging.error(f"Gmail polling error: {e}")


    async def run_forever(self):
        while True:
            await self.poll_gmail()
            logging.info(f"💤 Sloane is resting for {POLL_INTERVAL}s...")
            await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    commander = EmailCommander()
    asyncio.run(commander.run_forever())
