import time
import json
import logging
from playwright.sync_api import sync_playwright

# Setup secure audit logging (Gemini Directive)
logging.basicConfig(
    filename='audit_synapse.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class XLinkSynapse:
    """
    X-Link Synapse Core Engine
    Objective: Secure, stealthy CDP connection to existing Brave browser instances.
    """
    def __init__(self, cdp_url="http://localhost:9222"):
        self.cdp_url = cdp_url
        self.pw = None
        self.browser = None

    def connect(self):
        """Establish secure CDP link to Brave."""
        logging.info(f"Initiating CDP connection to {self.cdp_url}")
        self.pw = sync_playwright().start()
        try:
            # Stealth: connect_over_cdp is the stealthiest mode (no new browser launch)
            self.browser = self.pw.chromium.connect_over_cdp(self.cdp_url)
            logging.info("CDP Connection Established. Synapse Bridge is Online.")
            print("✅ Synapse Bridge Online.")
            return True
        except Exception as e:
            logging.error(f"Failed to connect to CDP: {e}")
            print(f"❌ Connection Failed: Have you launched Brave with --remote-debugging-port=9222?")
            return False

    def check_tabs(self):
        """Audit all open tabs for targeted DOM interaction."""
        if not self.browser:
            return []
        
        target_tabs = []
        for ctx in self.browser.contexts:
            for p in ctx.pages:
                target_tabs.append({"url": p.url, "title": p.title()})
        return target_tabs

    def extract_safe_dom(self, target_url_substring, selector):
        """
        Safely grab DOM handles without triggering navigator.webdriver.
        Avoids heavy page.evaluate() when possible, relying on native locators.
        """
        if not self.browser:
            return None
            
        for ctx in self.browser.contexts:
            for p in ctx.pages:
                if target_url_substring in p.url:
                    try:
                        p.bring_to_front()
                        time.sleep(1) # Human cadence
                        
                        # Use native locator to avoid execution context footprint
                        handles = p.locator(selector).all()
                        data = [h.inner_text() for h in handles]
                        
                        logging.info(f"Extracted {len(data)} nodes from {p.url} using selector '{selector}'")
                        return data
                    except Exception as e:
                        logging.error(f"DOM Extraction Failed on {p.url}: {e}")
                        return None
        return None

    def close(self):
        """Terminate the synapse connection cleanly."""
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()
        logging.info("Synapse Bridge Offline.")

if __name__ == "__main__":
    # Test Payload execution
    synapse = XLinkSynapse()
    if synapse.connect():
        tabs = synapse.check_tabs()
        print(f"Active Tabs Monitored: {len(tabs)}")
        synapse.close()
