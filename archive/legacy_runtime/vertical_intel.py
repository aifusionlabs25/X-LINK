import asyncio
import os
import json
from playwright.async_api import async_playwright

CDP_URL = "http://localhost:9222"

PROMPTS = {
    "grok.com": "Search realtime data for unfiltered sentiment regarding buying new construction homes in Phoenix right now. What are buyers complaining about most on X/Twitter? Are there delays, hidden fees, or poor communication from sales reps?",
    "perplexity.ai": "Search the web for the current state of AI adoption among major home builders in 2026. What specific software or incumbent CRM systems are they currently using for their sales funnels?",
    "gemini.google.com": "Analyze the legal and compliance risks for an AI Sales Concierge representing a Home Builder. If the AI hallucinates a lower interest rate, an incorrect base price, or a false timeline, what is the exact liability profile? Outline 3 strict guardrails to prevent this.",
    "chatgpt.com": "Assume the role of the X Agent Factory Dojo Master. Await the findings from Grok, Perplexity, and Gemini. I will provide those to you shortly. When you receive them, use them to generate the ultimate, highly-refined System Prompt for the Fulton Homes \"Sales Concierge\" agent"
}

async def trigger_prompt(page, domain, prompt):
    print(f"[{domain}] Injecting prompt...")
    await page.bring_to_front()
    await asyncio.sleep(1)

    try:
        if "grok.com" in domain:
            box = page.locator('textarea').last
            await box.fill(prompt)
            await page.keyboard.press('Enter')
        elif "perplexity.ai" in domain:
            box = page.locator('textarea').last
            await box.fill(prompt)
            await page.keyboard.press('Enter')
        elif "gemini.google.com" in domain:
            box = page.locator('rich-textarea p, .ql-editor, textarea').last
            await box.fill(prompt)
            await page.keyboard.press('Enter')
        elif "chatgpt.com" in domain:
            box = page.locator('#prompt-textarea')
            await box.fill(prompt)
            await page.keyboard.press('Enter')
        else:
            box = page.locator('textarea').last
            await box.fill(prompt)
            await page.keyboard.press('Enter')
        print(f"[{domain}] Prompt submitted successfully.")
    except Exception as e:
        print(f"[{domain}] Failed to submit prompt: {e}")

async def extract_response(page, domain):
    print(f"[{domain}] Extracting response DOM...")
    await page.bring_to_front()
    await asyncio.sleep(1)
    try:
        if "chatgpt.com" in domain:
            texts = await page.locator('[data-message-author-role="assistant"]').all_inner_texts()
            return texts[-1] if texts else await page.locator('.markdown').last.inner_text()
        elif "perplexity.ai" in domain:
            texts = await page.locator('.prose').all_inner_texts()
            return texts[-1] if texts else "No response found"
        elif "gemini.google.com" in domain:
            texts = await page.locator('message-content').all_inner_texts()
            return texts[-1] if texts else "No response found"
        elif "grok.com" in domain:
            texts = await page.locator('.prose, [class*="message"], p').all_inner_texts()
            # grok can be tricky, let's grab the last chunk that's long enough
            valid_texts = [t for t in texts if len(t) > 50]
            return valid_texts[-1] if valid_texts else "No response found"
        else:
            return await page.evaluate("document.body.innerText")
    except Exception as e:
        print(f"[{domain}] Extraction error: {e}")
        return f"Extraction error: {e}"

async def main():
    async with async_playwright() as p:
        try:
            print(f"Connecting to Brave at {CDP_URL}...")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"Failed to connect to browser CDP: {e}")
            return
            
        contexts = browser.contexts
        if not contexts:
            print("No contexts found.")
            return
            
        context = contexts[0]
        targets = {}
        for page in context.pages:
            url = page.url
            for key in PROMPTS:
                if key in url and key not in targets:
                    targets[key] = page
                    
        print(f"Found {len(targets)} matching tabs out of 4: {list(targets.keys())}")
        
        # Stage 1: Inject initial prompts into all 4 tabs concurrently
        tasks = []
        for key, page in targets.items():
            tasks.append(trigger_prompt(page, key, PROMPTS[key]))
            
        await asyncio.gather(*tasks)
        print("All Phase 1 Prompts injected. Waiting 45 seconds for generation...")
        await asyncio.sleep(45)
        
        # Stage 2: Extract from Grok, Perplexity, Gemini
        findings = {}
        for key in ["grok.com", "perplexity.ai", "gemini.google.com"]:
            if key in targets:
                res = await extract_response(targets[key], key)
                findings[key] = res
                
        # Consolidate findings
        consolidated_findings = f"""Here are the findings from the research agents:

--- GROK (Unfiltered Pulse) ---
{findings.get('grok.com', 'No data')}

--- PERPLEXITY (Deep Researcher) ---
{findings.get('perplexity.ai', 'No data')}

--- GEMINI (Policy Auditor) ---
{findings.get('gemini.google.com', 'No data')}

Now, generate the ultimate, highly-refined System Prompt for the Fulton Homes "Sales Concierge" agent."""

        with open("intel_report_raw.txt", "w", encoding="utf-8") as f:
            for k, v in findings.items():
                f.write(f"=== {k.upper()} ===\n{v}\n\n")

        print("Phase 2: Injecting consolidated findings into ChatGPT...")
        if "chatgpt.com" in targets:
            gpt_page = targets["chatgpt.com"]
            # To handle long text filling in textarea
            # It might be safer to use clipboard or chunked fill, but let's try fill first
            await gpt_page.bring_to_front()
            await asyncio.sleep(1)
            box = gpt_page.locator('#prompt-textarea')
            await box.fill(consolidated_findings)
            await asyncio.sleep(1)
            await gpt_page.keyboard.press('Enter')
            
            print("Waiting 45 seconds for ChatGPT to synthesize system prompt...")
            await asyncio.sleep(45)
            
            final_prompt = await extract_response(gpt_page, "chatgpt.com")
            with open("intel_report_raw.txt", "a", encoding="utf-8") as f:
                f.write(f"=== CHATGPT SYNTHESIS (FINAL PROMPT) ===\n{final_prompt}\n\n")
            print("Complete! Final prompt saved.")
        else:
            print("ChatGPT tab not found to inject finals.")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
