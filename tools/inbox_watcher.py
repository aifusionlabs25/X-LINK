import asyncio
import os
import sys
import random
import logging
import subprocess
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Path setup
SCRIP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIP_DIR)
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

async def watch_inbox():
    engine = XLinkEngine()
    if not await engine.connect():
        logging.error("❌ Failed to connect to Brave CDP.")
        return

    # LOCK TO EXPLICIT ACCOUNT (Absolute Address + Account Awareness)
    ACCOUNT = "novaaifusionlabs@gmail.com"
    url = f"https://mail.google.com/mail/u/{ACCOUNT}/#inbox"
    page = await engine.ensure_page(url, account_email=ACCOUNT)

    try:
        while True:
            try:
                logging.info(f"[INBOX] Polling for directives at {datetime.now().strftime('%H:%M:%S')}...")
                
                # RELOAD WITH LENIENT WAIT (Gmail is heavy)
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(8)
                
                # ESCAPE OPEN THREADS: Click the "Inbox" link to ensure list view
                try:
                    inbox_link = page.locator('a[title^="Inbox"]').first
                    if await inbox_link.is_visible():
                        await inbox_link.click()
                        await asyncio.sleep(random.uniform(3, 5))
                except Exception as e:
                    logging.warning(f"Inbox escape click bypassed: {e}")

                # Capture all potential subject-bearing elements
                subject_elements = await page.locator('span.bog').all()
                
                for el in subject_elements:
                    subject = await el.inner_text()
                    row = el.locator('xpath=ancestor::tr')
                    row_class = await row.get_attribute("class") or ""
                    
                    is_unread = "zE" in row_class
                    if not is_unread:
                        continue
                    
                    preview_text = ""
                    try:
                        preview_el = row.locator('span.y2')
                        preview_text = await preview_el.inner_text()
                    except:
                        pass
                        
                    logging.info(f"📧 [UNREAD FOUND] Subj: '{subject}' | Preview: '{preview_text[:30]}...'")
                    
                    # Detect Directive (Keywords: Sloane, COMMAND:)
                    search_str = (subject + " " + preview_text).upper()
                    if "COMMAND:" in search_str or "SLOANE" in search_str:
                        logging.info(f"⚡ [DIRECTIVE DETECTED] Processing: {subject}")
                        
                        # 1. Open the email (Stealth Click)
                        await engine.human_click(page, f'span:has-text("{subject}")')
                        await asyncio.sleep(random.uniform(4, 6)) 
                        
                        # 2. Extract Body
                        body_locator = page.locator('div[role="listitem"] [dir="ltr"]').last
                        body_text = await body_locator.inner_text()
                        
                        upper_body = body_text.upper()
                        response_msg = ""
                        
                        # 3. Directive Selection
                        if "AUDIT" in upper_body:
                            subprocess.Popen([sys.executable, "tools/usage_auditor.py"])
                            response_msg = "Audit initialized, Founder. I've updated the Hub with the latest intelligence. Do try to keep up."
                        elif any(k in upper_body for k in ["STATUS", "BRIEFING", "UPDATE"]):
                            subprocess.Popen([sys.executable, "tools/executive_briefing.py", "--email"])
                            response_msg = f"Your briefing has been synthesized and delivered, Founder. Precision is my specialty. (Processed at {datetime.now().strftime('%H:%M')})"
                        else:
                            response_msg = "I received your transmission, but the directive was... unclear. Do be more specific next time."

                        # 4. Sassy Reply (Stealth Type + Fail-Safe Send)
                        logging.info("✍️ Drafting Sassy Reply...")
                        try:
                            # Click Reply
                            await engine.human_click(page, 'span[role="link"]:has-text("Reply")')
                            await asyncio.sleep(random.uniform(2, 3))
                            
                            # Type Reply
                            reply_box = 'div[role="textbox"]'
                            await engine.human_type(page, reply_box, response_msg)
                            await asyncio.sleep(random.uniform(1, 2))
                            
                            # Fail-Safe Send Sequence
                            logging.info("🚀 Triggering transmission...")
                            await page.keyboard.press("Control+Enter")
                            await asyncio.sleep(2)
                            
                            # Click Fallback (Verification)
                            send_btn = page.locator('div[role="button"][aria-label^="Send"]').first
                            if await send_btn.is_visible():
                                await engine.human_click(page, 'div[role="button"][aria-label^="Send"]')
                            
                            logging.info("✅ Response delivered via stealth channel.")
                        except Exception as reply_err:
                            logging.error(f"❌ Reply flow failed: {reply_err}")
                        
                        # Restore State
                        await page.goto(url)
                        await asyncio.sleep(random.uniform(2, 3))
                        break # Re-poll after an interaction
                    
                # Standard Loop Delay (Stealth Polling)
                poll_wait = random.randint(300, 900) # 5-15 mins
                logging.info(f"[INBOX] Next poll in {poll_wait//60} minutes.")
                await asyncio.sleep(poll_wait)

            except Exception as e:
                logging.error(f"Error during poll: {e}")
                await asyncio.sleep(30)

    except Exception as e:
        logging.error(f"Fatal error in watcher: {e}")
    finally:
        await engine.close()

if __name__ == "__main__":
    asyncio.run(watch_inbox())
