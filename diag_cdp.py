import asyncio
from playwright.async_api import async_playwright

async def test_cdp():
    print("Attempting to connect to CDP on 127.0.0.1:9222...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            print(f"Connected! Contexts: {len(browser.contexts)}")
            context = browser.contexts[0]
            print(f"Pages: {len(context.pages)}")
            for page in context.pages:
                print(f" - {page.url}")
            await browser.close()
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_cdp())
