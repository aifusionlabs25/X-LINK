import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        # Connect to existing browser
        browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        
        for dom_target in ["grok.com", "perplexity.ai"]:
            page = next((p for p in context.pages if dom_target in p.url), None)
            if not page:
                print(f"{dom_target} tab not found.")
                continue
            
            print(f"--- {dom_target} ---")
            elements = await page.locator('[contenteditable="true"], textarea, input[type="text"]').element_handles()
            for i, el in enumerate(elements):
                tag_name = await el.evaluate("node => node.tagName")
                is_visible = await el.is_visible()
                placeholder = await el.get_attribute("placeholder")
                print(f"[{i}] tag={tag_name}, visible={is_visible}, placeholder='{placeholder}'")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
