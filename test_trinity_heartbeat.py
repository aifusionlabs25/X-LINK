import asyncio
import os
import sys

# Path setup
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

def log_to_file(text):
    with open("trinity_heartbeat_results.txt", "a", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)

async def test_heartbeat():
    if os.path.exists("trinity_heartbeat_results.txt"):
        os.remove("trinity_heartbeat_results.txt")
        
    engine = XLinkEngine()
    log_to_file("💓 Trinity Heartbeat Test")
    
    if not await engine.connect():
        log_to_file("❌ FAILED: Browser not connected (CDP 9222).")
        log_to_file("💡 HINT: Please run 'Sloane_Stealth_Launcher.bat' on your Desktop and try again.")
        return

    platforms = ["perplexity.ai", "gemini.google.com", "grok.com"]
    
    for domain in platforms:
        log_to_file(f"\n📡 Testing {domain}...")
        page = engine._get_page_by_domain(domain)
        if not page:
            log_to_file(f" ⚠️  {domain} tab not found. Use Hub to open it first.")
            continue
            
        log_to_file(f" ✅ Tab found: {await page.title()}")
        # Check if we can find ANY of the selectors we added
        test_selectors = {
            "perplexity.ai": ['textarea[placeholder*="Ask"]', 'textarea', '[contenteditable="true"]'],
            "gemini.google.com": ['.ql-editor', 'rich-textarea p', '[contenteditable="true"]', 'textarea'],
            "grok.com": ['[contenteditable="true"]', 'textarea', '.prose-editor']
        }
        
        found = False
        for s in test_selectors[domain]:
            try:
                if await page.locator(s).count() > 0:
                    log_to_file(f" ✅ SELECTOR MATCH: {s}")
                    found = True
                    break
            except: pass
            
        if not found:
            log_to_file(f" ❌ NO SELECTOR MATCHES FOUND for {domain}. Site UI may have changed extremely.")

    await engine.close()

if __name__ == "__main__":
    asyncio.run(test_heartbeat())
