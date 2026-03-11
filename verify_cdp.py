import asyncio
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"

async def main():
    print(f"Connecting to Brave at {CDP_URL}...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            contexts = browser.contexts
            if not contexts:
                print("No contexts found.")
                return

            context = contexts[0]
            print(f"Connected successfully. Found {len(context.pages)} total tabs.")
            
            targets = ["grok.com", "perplexity.ai", "gemini.google.com", "chatgpt.com"]
            found_targets = []
            
            for page in context.pages:
                url = page.url
                for t in targets:
                    if t in url and t not in found_targets:
                        found_targets.append(t)
                        print(f"Target found: {t} at {url}")
            
            print(f"\nFound {len(found_targets)}/4 required targets: {found_targets}")
            if len(found_targets) == 4:
                print("SUCCESS: All targets are running and visible via CDP.")
            else:
                print("WARNING: Missing some required targets.")
                
            await browser.close()
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    asyncio.run(main())
