import asyncio
import os
import sys
import argparse
import logging
import re
import string
import json
import yaml
from datetime import datetime
import requests

# Link up to the local framework
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

# Define Vault Log Path
LOG_PATH = os.path.join(ROOT_DIR, "vault", "logs", "sloane_operations.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Shared logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

VAULT_DIR = os.path.join(ROOT_DIR, 'vault', 'archives')

# Load Configurations
PARAMS_PATH = os.path.join(ROOT_DIR, "config", "archival_params.yaml")
SELECTORS_PATH = os.path.join(ROOT_DIR, "config", "archival_selectors.json")

try:
    with open(PARAMS_PATH, "r", encoding="utf-8") as f:
        ARCHIVAL_PARAMS = yaml.safe_load(f)
except Exception:
    ARCHIVAL_PARAMS = {"projects": [], "ignore_titles": []}

try:
    with open(SELECTORS_PATH, "r", encoding="utf-8") as f:
        SELECTORS = json.load(f)
except Exception:
    SELECTORS = {}

TARGETS = {
    "chatgpt": {
        "url": "https://chatgpt.com",
        "name": "ChatGPT"
    },
    "perplexity": {
        "url": "https://www.perplexity.ai",
        "name": "Perplexity"
    },
    "gemini": {
        "url": "https://gemini.google.com/app",
        "name": "Gemini"
    },
    "grok": {
        "url": "https://grok.com",
        "name": "Grok"
    }
}

class LLMArchivist:
    def __init__(self):
        self.engine = XLinkEngine()
        os.makedirs(VAULT_DIR, exist_ok=True)

    async def connect(self):
        logging.info("🧠 Initializing The Great Archivist engine...")
        return await self.engine.connect()

    async def disconnect(self):
        await self.engine.close()

    def _sanitize_filename(self, text):
        valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
        cleaned = ''.join(c for c in text if c in valid_chars)
        return cleaned.strip()[:50] or "untitled_session"

    def _trigger_intervention(self, service_name, url, issue):
        """POSTs a Founder Intervention Alert to the Hub."""
        logging.warning(f"🚨 SECURITY WALL DETECTED: {issue} at {service_name}")
        try:
            requests.post("http://127.0.0.1:5001/api/intervention", json={
                "url": url,
                "service": service_name,
                "issue": issue,
                "message": f"Founder, I'm stuck at the {service_name} gate due to a {issue}. Please handle the MFA/Login and click 'Resume Mission' so I can finish the archive."
            }, timeout=5)
        except Exception as e:
            logging.error(f"Failed to post intervention alert: {e}")

    async def _wait_for_intervention(self):
        """Blocks execution until the Hub reports no active intervention."""
        logging.info("⏸️ Archivist Paused. Waiting for Founder to click 'Resume Mission' on the Hub...")
        while True:
            try:
                resp = requests.get("http://127.0.0.1:5001/api/intervention", timeout=5)
                data = resp.json()
                if not data.get("active"):
                    logging.info("🔌 Intervention Cleared. Resuming mission...")
                    return True
            except Exception as e:
                logging.error(f"Intervention poll failed: {e}")
            
            await asyncio.sleep(2) # Poll every 2 seconds

    async def _archive_page_content(self, page, platform_name):
        """Extracts the targeted chat content and routes to Dual-Vault."""
        try:
            # 1. Grab the Title
            title = await page.title()
            safe_title = self._sanitize_filename(title)
            
            # Check Ignore List
            ignore_titles = ARCHIVAL_PARAMS.get("ignore_titles", [])
            if any(ign.lower() == title.lower() for ign in ignore_titles):
                logging.info(f"Skipping ignored title: {title}")
                return None

            # 2. Determine Routing (Project vs Private)
            vault_tier = "private"
            project_subfolder = ""
            for proj in ARCHIVAL_PARAMS.get("projects", []):
                if any(kw.lower() in title.lower() for kw in proj.get("keywords", [])):
                    vault_tier = "projects"
                    project_subfolder = self._sanitize_filename(proj.get("name", "Unknown"))
                    break
                    
            # 3. Targeted Extraction
            platform_key = platform_name.lower()
            content = ""
            
            if platform_key in SELECTORS:
                sel = SELECTORS[platform_key]
                try:
                    # Wait for message containers to ensure page loaded
                    await page.wait_for_selector(sel["message_containers"], timeout=5000)
                    containers = await page.locator(sel["message_containers"]).all()
                    
                    dialogue = []
                    for c in containers:
                        USER_TEXT = "\n".join(await c.locator(sel["user_message_text"]).all_inner_texts()) if await c.locator(sel["user_message_text"]).count() > 0 else None
                        AI_TEXT = "\n".join(await c.locator(sel["ai_message_text"]).all_inner_texts()) if await c.locator(sel["ai_message_text"]).count() > 0 else None
                        
                        if USER_TEXT:
                            dialogue.append(f"#### [User]:\n{USER_TEXT.strip()}\n")
                        if AI_TEXT:
                            dialogue.append(f"#### [{platform_name}]:\n{AI_TEXT.strip()}\n")
                            
                    content = "\n".join(dialogue)
                except Exception as e:
                    logging.warning(f"Targeted extraction failed for {platform_name}, falling back to raw body text. ({e})")
                    content = await page.inner_text('body')
            else:
                content = await page.inner_text('body')
            
            # Formatting
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.now().strftime("%H:%M:%S")
            file_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 4. Save to Dual-Vault directory
            if vault_tier == "projects":
                target_dir = os.path.join(VAULT_DIR, "projects", project_subfolder, platform_key)
            else:
                target_dir = os.path.join(VAULT_DIR, "private", platform_key)
                
            os.makedirs(target_dir, exist_ok=True)
            file_path = os.path.join(target_dir, f"{safe_title}_{file_stamp}.md")
            
            routing_badge = f"PROJECT: {project_subfolder}" if vault_tier == "projects" else "PRIVATE VAULT"
            
            header = f"# Session Archive: {title}\n"
            header += f"**[DATE: {date_str}] [TIME: {time_str}] [PLATFORM: {platform_name}] [ROUTING: {routing_badge}]**\n\n"
            header += "---\n\n"
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(header + content)
                
            logging.info(f"✅ Archived session to {routing_badge}: {file_path}")
            return file_path

            
        except Exception as e:
            logging.error(f"❌ Failed to archive {platform_name}: {e}")
            return None

    async def run_archival_sweep(self, platforms=None, target_keyword=None, args_limit=15):
        """Runs the main archival loop across chosen platforms."""
        if not platforms:
            platforms = list(TARGETS.keys())
            
        logging.info(f"🚀 Commencing Great Archivist Sweep on targets: {', '.join(platforms)}")
        if target_keyword:
            logging.info(f"🔍 Keyword Filter Active: '{target_keyword}'")
        
        for key in platforms:
            if key not in TARGETS:
                logging.warning(f"Unknown platform '{key}', skipping.")
                continue
                
            target = TARGETS[key]
            name = target["name"]
            url = target["url"]
            email = target.get("email")
            
            logging.info(f"------------\n📡 Targeting {name} at {url}...")
            
            page = await self.engine.ensure_page(url, wait_sec=5, account_email=email)
            await page.bring_to_front()
            
            # Check for MFA / Login walls
            wall_issue = await self.engine.detect_security_wall(page)
            
            # GROK-SPECIFIC LOGIN CHECK (X.com Session)
            if key == "grok" and not wall_issue:
                if await page.locator('button:has-text("Log in")').count() > 0:
                    wall_issue = "Login Required"

            if wall_issue:
                self._trigger_intervention(name, url, wall_issue)
                await self._wait_for_intervention()
                # Re-verify after resume to ensure session is actually live now
                logging.info(f"🔄 Re-verifying {name} session after Founder intervention...")
                page = await self.engine.ensure_page(url, wait_sec=5, account_email=email)
                continue # Retry this platform loop iteration
                
            logging.info(f"🔓 Security cleared for {name}. Extracting session data...")
            await asyncio.sleep(3) # Let dynamic React content load
            
            # CHATGPT SPECIFIC: Route to X Agents project
            if key == "chatgpt":
                logging.info("Routing ChatGPT into the 'X Agents' project space...")
                try:
                    # Try text, aria-label, and common project hrefs
                    selectors = [
                        'text="X Agents"',
                        '[aria-label*="X Agents"]',
                        'a[href*="/g/g-"]' # Projects often have this format
                    ]
                    
                    clicked = False
                    for s in selectors:
                        link = page.locator(s).first
                        if await link.count() > 0:
                            logging.info(f"Clicking X Agents project space via selector: {s}")
                            await link.click()
                            await asyncio.sleep(5)
                            clicked = True
                            break
                    
                    if not clicked:
                        logging.warning("Could not identify 'X Agents' project link. Defaulting to main history.")
                except Exception as e:
                    logging.debug(f"X Agents routing failed: {e}")
            
            # Attempt to click sidebars for multi-conversation sweeps
            if key in SELECTORS:
                sel = SELECTORS[key]
                sidebar_items = page.locator(sel["list_of_titles"])
                count = await sidebar_items.count()
                
                if count > 0:
                    try:
                        sweep_limit = int(args_limit)
                    except (ValueError, TypeError):
                        sweep_limit = count if str(args_limit).lower() == "all" else 15
                    
                    actual_limit = min(count, sweep_limit)
                    logging.info(f"Found {count} sidebar history items. Scanning top {actual_limit} items...")
                    
                    for i in range(actual_limit):
                        item = sidebar_items.nth(i)
                        
                        try:
                            # Depending on platform, the text might be inside a child span
                            title_text = ""
                            if await item.locator(sel["title_text"]).count() > 0:
                                title_text = await item.locator(sel["title_text"]).first.inner_text()
                            else:
                                title_text = await item.inner_text()
                                
                            if not title_text.strip():
                                continue
                                
                            if target_keyword and target_keyword.lower() not in title_text.lower():
                                continue # Skip if filter active
                                
                            logging.info(f"Extracting history match: '{title_text.strip()}'")
                            await item.click()
                            await asyncio.sleep(4) # Wait for conversation to load
                            await self._archive_page_content(page, name)
                        except Exception as e:
                            logging.debug(f"Skipping unclickable sidebar item: {e}")
                            
            # Always scrape the currently active main page anyway
            await self._archive_page_content(page, name)
            
        logging.info("🏁 Great Archivist Sweep complete.")

    async def run_heartbeat_janitor(self):
        """The persistent background loop to keep sessions alive."""
        logging.info("🩺 Starting Heartbeat Janitor (Ctrl+C to stop)...")
        while True:
            for key, target in TARGETS.items():
                name = target["name"]
                url = target["url"]
                
                logging.info(f"💓 Pinging {name} to maintain session persistence...")
                try:
                    # Just load the page to bump the auth cookie
                    page = await self.engine.ensure_page(url, wait_sec=2, account_email=target.get("email"))
                    # Perform a micro-action (trigger scroll to simulate activity)
                    await page.evaluate("window.scrollBy(0, 50)")
                except Exception as e:
                    logging.warning(f"⚠️ Heartbeat ping failed for {name}: {e}")
                    
            # Sleep for 45 minutes between heartbeats
            await asyncio.sleep(45 * 60)

async def main():
    parser = argparse.ArgumentParser(description="The Great Archivist")
    parser.add_argument("--platform", type=str, help="Specific platform to archive (chatgpt, perplexity, gemini, grok)")
    parser.add_argument("--keyword", type=str, help="Only archive conversations matching this keyword in title")
    parser.add_argument("--limit", type=str, default="15", help="Number of sidebar items to scan, or 'all'")
    parser.add_argument("--heartbeat", action="store_true", help="Run the continuous Heartbeat Janitor loop")
    args = parser.parse_args()

    archivist = LLMArchivist()
    if not await archivist.connect():
        return

    try:
        if args.heartbeat:
            await archivist.run_heartbeat_janitor()
        else:
            platforms = [args.platform.lower()] if args.platform else None
            await archivist.run_archival_sweep(platforms, args.keyword, args.limit)
    finally:
        if not args.heartbeat:
            await archivist.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
