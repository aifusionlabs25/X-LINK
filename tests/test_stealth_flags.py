import asyncio
import logging
from playwright.async_api import async_playwright

async def verify_stealth():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            page = await context.new_page()
            
            # Check for automation flag
            is_automated = await page.evaluate("navigator.webdriver")
            print(f"--- STEALTH CHECK ---")
            print(f"navigator.webdriver: {is_automated}")
            
            if is_automated:
                print("FAIL: Automation detection is ON. Cloudflare will likely block.")
            else:
                print("SUCCESS: Automation detection is suppressed! Sloane is now invisible.")
            
            await page.close()
            await browser.close()
        except Exception as e:
            print(f"Error connecting: {e}")

if __name__ == "__main__":
    asyncio.run(verify_stealth())
