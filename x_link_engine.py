import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Page

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def setup_operational_logger(log_file):
    logger = logging.getLogger("sloane_ops")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(fh)
    return logger

class XLinkEngine:
    """
    X-Link Mode-Based Engine (V2)
    A versatile orchestration layer for CDP-connected browser instances.
    """
    def __init__(self, cdp_url="http://127.0.0.1:9222"):
        self.cdp_url = cdp_url
        self.pw = None
        self.browser = None
        self.context = None
        self.vault_dir = "vault"
        self._ensure_vault()
        self.action_lock = asyncio.Lock()
        
        # Operational Logging
        log_dir = os.path.join(self.vault_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        self.ops_log = setup_operational_logger(os.path.join(log_dir, "sloane_operations.log"))

    def _ensure_vault(self):
        for d in ["sessions", "intel", "reports", "artifacts", "communications"]:
            os.makedirs(os.path.join(self.vault_dir, d), exist_ok=True)

    def _save_to_vault(self, category: str, filename: str, content: str):
        path = os.path.join(self.vault_dir, category, filename)
        mode = "a" if category == "sessions" else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        logging.info(f"Saved to vault: {path}")

    async def connect(self):
        logging.info(f"Connecting to CDP at {self.cdp_url} ...")
        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.connect_over_cdp(self.cdp_url)
            if self.browser.contexts:
                self.context = self.browser.contexts[0]
            logging.info("Connected successfully.")
            return True
        except Exception as e:
            logging.error(f"Failed to connect: {e}")
            return False

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        logging.info("Engine Shutdown.")

    async def get_page_by_account(self, email: str) -> Page | None:
        """Retrieves a page matching both the domain and the account email in the title/metadata."""
        if not self.context:
            return None
        for page in self.context.pages:
            try:
                title = await page.title()
                if email in title or email in page.url:
                    return page
            except:
                continue
        return None

    def _get_page_by_domain(self, domain: str) -> Page | None:
        if not self.context:
            return None
        for page in self.context.pages:
            if domain in page.url:
                return page
        return None

    async def cleanup_tabs(self, keep_list: list[str] = None):
        """
        Purges non-essential tabs. 
        keep_list: List of domains or URL fragments to preserve.
        """
        if not self.context:
            return
            
        keep_list = keep_list or []
        # Always keep the hub and basic google services if needed
        essential = ["audit_hub.html", "mail.google.com", "calendar.google.com"]
        all_keep = keep_list + essential
        
        pages = self.context.pages
        logging.info(f"[TAB-MANAGER] Reviewing {len(pages)} open tabs...")
        
        for page in pages:
            url = page.url
            should_close = True
            for k in all_keep:
                if k in url:
                    should_close = False
                    break
            
            if should_close:
                logging.info(f"[TAB-MANAGER] Closing non-essential tab: {url}")
                try:
                    await page.close()
                except Exception as e:
                    logging.warning(f"Failed to close tab {url}: {e}")

    async def ensure_page(self, url: str, wait_sec: int = 5, bring_to_front: bool = True, account_email: str = None) -> Page:
        """
        Auto-Tab Recovery with Email-Based Targeting.
        Forces Google services to use the specific account session via URL.
        """
        from urllib.parse import urlparse
        
        # 1. Transform URL if it's a Google Service and account_email is provided
        if account_email and ("google.com" in url or "gmail.com" in url):
            if "/u/" in url:
                # Replace index (e.g. /u/0/) with email (e.g. /u/user@gmail.com/)
                url = re.sub(r'/u/\d+/', f'/u/{account_email}/', url)
            else:
                # Inject email-based path if missing
                if "mail.google.com" in url:
                    url = url.replace("mail.google.com/mail/", f"mail.google.com/mail/u/{account_email}/")
                elif "calendar.google.com" in url:
                    url = url.replace("calendar.google.com/calendar/", f"calendar.google.com/calendar/u/{account_email}/")

        domain = urlparse(url).netloc
        
        page = None
        if account_email:
            page = await self.get_page_by_account(account_email)
            if page:
                logging.info(f"[TAB-RECOVERY] Found existing tab for account: {account_email}")
        
        if not page:
            page = self._get_page_by_domain(domain)
            if page:
                logging.info(f"[TAB-RECOVERY] Found existing tab for domain: {domain}")
        
        if page:
            if bring_to_front:
                await page.bring_to_front()
            
            # AGGRESSIVE ENFORCEMENT: If it's a Google service and we HAVE a target email, 
            # but the email isn't in the current URL (or there's a numeric index), force redirect.
            if account_email and ("google.com" in page.url or "gmail.com" in page.url):
                current_url = page.url
                needs_redirect = False
                
                if account_email not in current_url:
                    needs_redirect = True
                elif "/u/" in current_url and not re.search(f'/u/{re.escape(account_email)}/', current_url):
                    needs_redirect = True
                
                if needs_redirect:
                    self.ops_log.info(f"[ACCOUNT-GUARD] Forcing absolute email URL redirect: {url}")
                    logging.info(f"[ACCOUNT-GUARD] Redirecting to email-based URL: {url}")
                    await page.goto(url)
            
            # HARD ENFORCEMENT: Verify session identity after load
            if account_email and ("google.com" in page.url or "gmail.com" in page.url):
                is_valid = await self.verify_gsuite_session(page, account_email)
                if not is_valid:
                    self.ops_log.info(f"[ACCOUNT-GUARD] HARD FAIL: Wrong session detected. Killing tab.")
                    logging.warning(f"[ACCOUNT-GUARD] Session identity mismatch. Terminating tab for safety.")
                    await page.close()
                    # Recursively try one more time with a fresh tab and forced email URL
                    return await self.ensure_page(url, wait_sec, bring_to_front, account_email)

            await self.detect_security_wall(page)
            return page
            
        # Open a new tab
        logging.info(f"[TAB-RECOVERY] No tab found for {domain} — opening new tab to {url}")
        page = await self.context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(wait_sec)
        
        # Security Handshake
        await self.detect_security_wall(page)
        
        self.ops_log.info(f"[NAVIGATE] Target: {url} | Account: {account_email or 'Default'}")
        logging.info(f"[TAB-RECOVERY] Opened and loaded: {url}")
        return page

    async def switch_google_account(self, page: Page, target_email: str):
        """
        Verifies the active Google account and attempts to switch if it doesn't match.
        """
        logging.info(f"[ACCOUNT-GUARD] Verifying active account for {target_email}...")
        try:
            # 1. Check current account via the avatar/account button
            # Gmail/Calendar top right avatar
            account_btn = page.locator('a[aria-label*="Google Account"], button[aria-label*="Google Account"]').first
            
            # If not found immediately, wait a bit
            if not await account_btn.is_visible():
                await asyncio.sleep(2)
                
            label = await account_btn.get_attribute("aria-label") or ""
            if target_email.lower() in label.lower():
                logging.info(f"[ACCOUNT-GUARD] Verified: Already logged into {target_email}")
                return True
                
            logging.warning(f"[ACCOUNT-GUARD] Account mismatch! Current: {label}. Switching to {target_email}...")
            
            # 2. Click avatar to open account list
            await account_btn.click()
            await asyncio.sleep(2)
            
            # 3. Look for target email in the list
            target_selector = f'div:has-text("{target_email}")' # Broad search for the email text
            account_entry = page.locator(target_selector).first
            
            if await account_entry.is_visible():
                await account_entry.click()
                logging.info(f"[ACCOUNT-GUARD] Clicked account entry for {target_email}")
                await asyncio.sleep(5) # Wait for reload
                return True
            else:
                logging.error(f"[ACCOUNT-GUARD] Could not find {target_email} in account list.")
                # Fallback: Attempt forced index navigation if possible
                # This is a guess, but /u/1/ is often the second account
                if "/u/0/" in page.url:
                    new_url = page.url.replace("/u/0/", "/u/1/")
                    logging.info(f"[ACCOUNT-GUARD] Attempting index fallback to {new_url}")
                    await page.goto(new_url)
                    await asyncio.sleep(5)
                return False
                
        except Exception as e:
            logging.error(f"[ACCOUNT-GUARD] Error during account switching: {e}")
            return False

    async def verify_gsuite_session(self, page, target_email):
        """
        Hard verification of the active Google account.
        Scrapes the profile icon to ensure we are in the correct session.
        """
        try:
            # Check aria-label of the profile button (usually top right)
            # Format: "Google Account: Name (email@gmail.com)"
            profile_btn = page.locator('a[href*="SignOutOptions"], [aria-label*="Google Account"]').first
            if await profile_btn.count() > 0:
                label = await profile_btn.get_attribute("aria-label")
                if label and target_email in label:
                    return True
                
                title = await profile_btn.get_attribute("title")
                if title and target_email in title:
                    return True

            # Fallback: Check for any text on page containing the email (less reliable but good backup)
            content = await page.content()
            if f"({target_email})" in content:
                return True
                
            return False
        except Exception as e:
            logging.error(f"[ACCOUNT-GUARD] Verification error: {e}")
            return True # Default to True to prevent infinite loops if UI is lagging

    # ------------------------------------------------------------------
    # STEALTH / HUMAN EMULATION (Anti-Detection)
    # ------------------------------------------------------------------
    async def human_type(self, page: Page, selector: str, text: str):
        """Types text with randomized intervals and occasional backspaces."""
        import random
        self.ops_log.info(f"[TYPE-START] Selector: {selector} | Text Length: {len(text)}")
        locator = page.locator(selector).last
        await locator.click()
        for char in text:
            await page.keyboard.type(char, delay=random.randint(50, 150))
            if random.random() < 0.05: # 5% chance of a small "thinking" pause
                await asyncio.sleep(random.uniform(0.5, 1.5))
        
        self.ops_log.info(f"[TYPE] Typed {len(text)} chars into {selector}")
        logging.info(f"[STEALTH] Human-typed {len(text)} chars into {selector}")

    async def human_click(self, page: Page, selector: str):
        """Moves mouse to element with randomized offset before clicking."""
        import random
        self.ops_log.info(f"[CLICK-START] Selector: {selector}")
        locator = page.locator(selector).last
        box = await locator.bounding_box()
        if box:
            # Move to a random point within the target box
            x = box['x'] + random.uniform(2, box['width'] - 2)
            y = box['y'] + random.uniform(2, box['height'] - 2)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.mouse.click(x, y)
            self.ops_log.info(f"[CLICK] Element: {selector} at ({x}, {y})")
            logging.info(f"[STEALTH] Human-clicked {selector} at ({x}, {y})")

    # ------------------------------------------------------------------
    # PLATFORM-SPECIFIC SELECTORS (Inject & Extract)
    # ------------------------------------------------------------------
    async def _inject(self, page: Page, domain: str, prompt: str):
        async with self.action_lock:
            await page.bring_to_front()
            await asyncio.sleep(1)
            if "chatgpt.com" in domain:
                box = page.locator('#prompt-textarea')
                await box.fill(prompt)
                await page.keyboard.press("Enter")
            elif "grok.com" in domain:
                box = page.locator('[contenteditable="true"]').last
                await box.fill(prompt)
                await page.keyboard.press("Enter")
            elif "perplexity.ai" in domain:
                box = page.locator('[contenteditable="true"], textarea').last
                await box.fill(prompt)
                await page.keyboard.press("Enter")
            elif "gemini.google.com" in domain:
                box = page.locator('rich-textarea p, .ql-editor, textarea').last
                await box.fill(prompt)
                await page.keyboard.press("Enter")
            else:
                box = page.locator('textarea').last
                await box.fill(prompt)
                await page.keyboard.press("Enter")
            logging.info(f"[{domain}] Prompt injected.")

    async def check_tab_health(self) -> list[dict]:
        """
        Scans open tabs for blocking states (MFA, Login required, etc.).
        Returns a list of problematic tabs.
        """
        if not self.context:
            return []
            
        problems = []
        for page in self.context.pages:
            issue = await self.detect_security_wall(page)
            if issue:
                problems.append({"url": page.url, "issue": issue})
        return problems

    async def detect_security_wall(self, page: Page) -> Optional[str]:
        """
        Scans for known login/MFA walls and returns the issue type.
        Now includes Bitwarden-based auto-login.
        """
        try:
            url = page.url
            
            # Google services always contain "Sign in" text even when authenticated.
            # The Account Guard handles Google auth via URL routing, so skip security
            # wall detection for known Google properties to avoid false positives.
            google_safe = ["mail.google.com", "calendar.google.com", "drive.google.com", 
                           "docs.google.com", "accounts.google.com"]
            if any(domain in url for domain in google_safe):
                return None
            
            content = await page.content()
            indicators = [
                ("Sign in", "Login Required"),
                ("Log in", "Login Required"),
                ("Two-factor authentication", "MFA Required"),
                ("Get a verification code", "MFA Required"),
                ("Verify identity", "MFA Required"),
                ("Enter code", "MFA Required"),
                ("MFA", "MFA Required"),
                ("<title>404", "404 Error"),
                ("<h1>404", "404 Error")
            ]
            
            for marker, issue in indicators:
                if marker in content:
                    # If it's a login wall and NOT a Google Service (which we handle via URL),
                    # try Bitwarden auto-fill if the domain looks like one we own/access.
                    if issue == "Login Required" and "google.com" not in url:
                        await self.login_via_bitwarden(page)
                    
                    self.ops_log.info(f"[SECURITY] Issue detected at {page.url}: {issue}")
                    return issue
                    
            return None
        except Exception as e:
            logging.warning(f"Security check failed: {e}")
            return None

    async def login_via_bitwarden(self, page: Page):
        """
        Triggers the Bitwarden auto-fill and login sequence (Control+Shift+L).
        """
        logging.info(f"[BITWARDEN-BRIDGE] Login wall detected at {page.url}. Triggering auto-fill...")
        try:
            # 1. Focus the page
            await page.bring_to_front()
            
            # 2. Trigger Bitwarden Auto-fill Shortcut (Default: Control+Shift+L)
            await page.keyboard.down("Control")
            await page.keyboard.down("Shift")
            await page.keyboard.press("L")
            await page.keyboard.up("Shift")
            await page.keyboard.up("Control")
            
            await asyncio.sleep(2)
            
            # 3. Press Enter to submit the form if auto-fill worked
            await page.keyboard.press("Enter")
            self.ops_log.info(f"[BITWARDEN] Auto-fill triggered at {page.url}")
            logging.info(f"[BITWARDEN-BRIDGE] Transmission dispatched. Awaiting redirection...")
            await asyncio.sleep(5)
            
        except Exception as e:
            logging.error(f"[BITWARDEN-BRIDGE] Failed to trigger Bitwarden: {e}")

    async def _extract(self, page: Page, domain: str) -> str:
        if "chatgpt.com" in domain:
            texts = await page.locator('div[data-message-author-role="assistant"]').all_inner_texts()
            return texts[-1] if texts else "No response found."
        elif "grok.com" in domain:
            texts = await page.locator('.prose, [data-testid="message-row"], p').all_inner_texts()
            valid_texts = [t for t in texts if len(t) > 50]
            return valid_texts[-1] if valid_texts else "No response found."
        elif "perplexity.ai" in domain:
            texts = await page.locator('.prose').all_inner_texts()
            return texts[-1] if texts else "No response found."
        elif "gemini.google.com" in domain:
            texts = await page.locator('message-content').all_inner_texts()
            return texts[-1] if texts else "No response found."
        else:
            return await page.evaluate("document.body.innerText")

    # ------------------------------------------------------------------
    # MODES
    # ------------------------------------------------------------------
    async def run_one_shot(self, domain: str, prompt: str, timeout_sec: int = 120, stability_sec: int = 5) -> str:
        """
        [ONE-SHOT MODE]
        Injects a prompt, waits for generation to start, and then polls the DOM.
        Generation is considered 'complete' when the extracted text length hasn't changed
        for `stability_sec` consecutive seconds.
        """
        page = self._get_page_by_domain(domain)
        if not page:
            raise ValueError(f"Tab for {domain} not found.")

        logging.info(f"[{domain} | ONE-SHOT] Starting task...")
        await self._inject(page, domain, prompt)

        # Wait a moment for generation to begin before we start analyzing stability
        logging.info(f"[{domain} | ONE-SHOT] Waiting for generation to begin...")
        await asyncio.sleep(5) 

        logging.info(f"[{domain} | ONE-SHOT] Polling for generation completeness (stability threshold: {stability_sec}s)...")
        
        last_length = -1
        stable_time = 0
        elapsed_time = 0
        poll_interval = 1.0

        while elapsed_time < timeout_sec:
            current_text = await self._extract(page, domain)
            current_length = len(current_text)

            # Ignore extremely short/empty responses while it's "thinking"
            if current_length > 50 and current_length == last_length:
                stable_time += poll_interval
                if stable_time >= stability_sec:
                    logging.info(f"[{domain} | ONE-SHOT] Generation complete (Text stable for {stability_sec}s).")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safename = domain.replace('.', '_')
                    self._save_to_vault("intel", f"{safename}_{timestamp}.txt", f"PROMPT:\n{prompt}\n\nRESPONSE:\n{current_text}")
                    try:
                        await page.screenshot(path=os.path.join(self.vault_dir, "artifacts", f"{safename}_{timestamp}.png"))
                    except Exception as e:
                        logging.warning(f"Failed to capture artifact screenshot: {e}")
                    return current_text
            else:
                stable_time = 0
                last_length = current_length

            await asyncio.sleep(poll_interval)
            elapsed_time += poll_interval

        logging.warning(f"[{domain} | ONE-SHOT] Timeout reached ({timeout_sec}s) before stability achieved.")
        final_text = await self._extract(page, domain)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safename = domain.replace('.', '_')
        self._save_to_vault("intel", f"{safename}_{timestamp}_TIMEOUT.txt", f"PROMPT:\n{prompt}\n\nRESPONSE:\n{final_text}")
        try:
            await page.screenshot(path=os.path.join(self.vault_dir, "artifacts", f"{safename}_{timestamp}_TIMEOUT.png"))
        except Exception:
            pass
        return final_text

    async def run_chat(self, domain: str):
        """
        [CHAT MODE]
        A continuous interactive session bridged through the terminal.
        """
        logging.info(f"[{domain} | CHAT MODE] Session initialized. Type 'exit' to quit.")
        page = self._get_page_by_domain(domain)
        if not page:
             logging.error(f"Tab for {domain} not found.")
             return
             
        import sys
        session_id = f"{domain.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        while True:
            # Simple async input wrapper
            prompt = await asyncio.to_thread(input, f"\n[{domain}] > ")
            if prompt.strip().lower() == 'exit':
                break
            if not prompt.strip():
                continue
                
            self._save_to_vault("sessions", f"{session_id}.txt", f"\n[{domain}] > {prompt}\n")
                
            logging.info(f"[{domain}] Executing ONE-SHOT...")
            try:
                result = await self.run_one_shot(domain, prompt, timeout_sec=90, stability_sec=3)
                print(f"\n--- RESPONSE ---\n{result}\n----------------\n")
                self._save_to_vault("sessions", f"{session_id}.txt", f"--- RESPONSE ---\n{result}\n----------------\n")
            except Exception as e:
                logging.error(f"Error during chat turn: {e}")

    async def run_scatter_gather(self, targets: dict, synthesis_target: str, synthesis_prompt: str, timeout_sec: int = 120) -> str:
        """
        [SCATTER-GATHER MODE]
        targets: Dictionary mapping domain -> prompt to inject.
        e.g. {"grok.com": "...", "perplexity.ai": "..."}
        """
        logging.info(f"[SCATTER-GATHER] Scattering prompts to {list(targets.keys())}...")
        
        # 1. Scatter (Concurrently run ONE-SHOT on all targets)
        tasks = []
        for domain, prompt in targets.items():
            tasks.append(self.run_one_shot(domain, prompt, timeout_sec=timeout_sec, stability_sec=5))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        findings = {}
        for domain, res in zip(targets.keys(), results):
            if isinstance(res, Exception):
                logging.error(f"[{domain}] Scatter task failed: {res}")
                findings[domain] = f"Error: {res}"
            else:
                findings[domain] = res
                
        # 2. Consolidate
        consolidated = ""
        for domain, text in findings.items():
            consolidated += f"\n\n--- {domain.upper()} ---\n{text}"
            
        final_prompt = f"{consolidated}\n\n{synthesis_prompt}"
        
        # 3. Gather (Run ONE-SHOT on synthesis target)
        logging.info(f"[SCATTER-GATHER] Gathering and sending to {synthesis_target} for synthesis...")
        final_result = await self.run_one_shot(synthesis_target, final_prompt, timeout_sec=timeout_sec, stability_sec=5)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._save_to_vault("reports", f"SCATTER_GATHER_REPORT_{timestamp}.txt", f"--- TARGETS ---\n{list(targets.keys())}\n\n--- SYNTHESIZED RESULT ---\n{final_result}")
        
        return final_result

    async def run_watcher(self, domain: str, poll_interval: int = 2):
        """
        [WATCHER MODE]
        Silently monitors a tab for changes without injecting anything.
        """
        logging.info(f"[{domain} | WATCHER MODE] Monitoring changes... (Ctrl+C to stop)")
        page = self._get_page_by_domain(domain)
        if not page:
             logging.error(f"Tab for {domain} not found.")
             return
             
        last_text = await self._extract(page, domain)
        try:
            while True:
                await asyncio.sleep(poll_interval)
                current_text = await self._extract(page, domain)
                if current_text != last_text and len(current_text) > 50:
                    logging.info(f"[{domain}] Change detected! Length changed from {len(last_text)} to {len(current_text)}.")
                    last_text = current_text
        except KeyboardInterrupt:
            logging.info("Watcher stopped.")
