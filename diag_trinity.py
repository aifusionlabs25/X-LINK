import asyncio
import os
import sys

# Path setup
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

def log_to_file(text):
    with open("diag_trinity_output.txt", "a", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)

async def diag():
    if os.path.exists("diag_trinity_output.txt"):
        os.remove("diag_trinity_output.txt")
        
    engine = XLinkEngine()
    log_to_file("🛰️ Connecting to X-LINK Synapse Bridge...")
    if not await engine.connect():
        print("❌ FAILED: Could not connect to CDP. Is Brave running on 9222?")
        return

    log_to_file("\n📜 ACTIVE TABS:")
    for page in engine.context.pages:
        log_to_file(f" - [{page.url}] {await page.title()}")

    targets = [
        {"name": "Perplexity", "domain": "perplexity.ai", "selector": "[contenteditable='true'], textarea"},
        {"name": "Gemini", "domain": "gemini.google.com", "selector": "rich-textarea p, .ql-editor, textarea"},
        {"name": "Grok", "domain": "grok.com", "selector": "[contenteditable='true']"}
    ]

    for t in targets:
        log_to_file(f"\n🔍 AUDITING {t['name']} ({t['domain']})...")
        page = engine._get_page_by_domain(t['domain'])
        if not page:
            log_to_file(f" ⚠️  Tab for {t['domain']} NOT FOUND.")
            continue
        
        # Test Selector
        try:
            count = await page.locator(t['selector']).count()
            if count > 0:
                log_to_file(f" ✅ Selector '{t['selector']}' found {count} matches.")
            else:
                log_to_file(f" ❌ Selector '{t['selector']}' NOT FOUND.")
        except Exception as e:
            log_to_file(f" ❌ Error checking selector: {e}")

    await engine.close()

if __name__ == "__main__":
    asyncio.run(diag())
