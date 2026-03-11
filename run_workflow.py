import time
import os
import sys
from playwright.sync_api import sync_playwright, expect

CDP_URL = "http://127.0.0.1:9222"

PROMPTS = {
    "grok.com": "Search realtime data for unfiltered sentiment regarding buying new construction homes in Phoenix right now. What are buyers complaining about most on X/Twitter? Are there delays, hidden fees, or poor communication from sales reps?",
    "perplexity.ai": "Search the web for the current state of AI adoption among major home builders in 2026. What specific software or incumbent CRM systems are they currently using for their sales funnels?",
    "gemini.google.com": "Analyze the legal and compliance risks for an AI Sales Concierge representing a Home Builder. If the AI hallucinates a lower interest rate, an incorrect base price, or a false timeline, what is the exact liability profile? Outline 3 strict guardrails to prevent this.",
    "chatgpt.com": "Assume the role of the X Agent Factory Dojo Master. Await the findings from Grok, Perplexity, and Gemini. I will provide those to you shortly. When you receive them, use them to generate the ultimate, highly-refined System Prompt for the Fulton Homes \"Sales Concierge\" agent."
}

def get_page_by_url_substring(browser, substring):
    for ctx in browser.contexts:
        for p in ctx.pages:
            if substring in p.url:
                return p
    return None

def inject_prompt(page, platform, prompt):
    print(f"[{platform}] Injecting prompt...")
    try:
        page.bring_to_front()
        time.sleep(1)
        if platform == "grok.com":
            page.mouse.click(600, 850) # Fallback click to focus
            time.sleep(1)
            page.keyboard.type(prompt)
            time.sleep(1)
            page.keyboard.press("Enter")
        elif platform == "perplexity.ai":
            # Perplexity usually auto-focuses, but let's be safe
            page.mouse.click(600, 850) 
            time.sleep(1)
            page.keyboard.type(prompt)
            time.sleep(1)
            page.keyboard.press("Enter")
        elif platform == "gemini.google.com":
            # Gemini has a specific rich text area
            box = page.locator('rich-textarea p, .ql-editor, textarea').last
            box.fill(prompt)
            page.keyboard.press("Enter")
        elif platform == "chatgpt.com":
            box = page.locator('#prompt-textarea')
            box.fill(prompt)
            page.keyboard.press("Enter")
        print(f"[{platform}] Prompt injected successfully.")
    except Exception as e:
        print(f"[{platform}] Failed to inject prompt: {e}")

def extract_response(page, platform):
    print(f"[{platform}] Extracting response...")
    try:
        page.bring_to_front()
        time.sleep(1)
        
        if platform == "grok.com":
            texts = page.locator('div.prose, [data-testid="message-row"]').all_inner_texts()
            valid_texts = [t for t in texts if len(t) > 50]
            return valid_texts[-1] if valid_texts else "No response found"
        elif platform == "perplexity.ai":
            texts = page.locator('.prose').all_inner_texts()
            return texts[-1] if texts else "No response found"
        elif platform == "gemini.google.com":
            texts = page.locator('message-content').all_inner_texts()
            return texts[-1] if texts else "No response found"
        elif platform == "chatgpt.com":
            texts = page.locator('div[data-message-author-role="assistant"]').all_inner_texts()
            return texts[-1] if texts else "No response found"
    except Exception as e:
        print(f"[{platform}] Extraction error: {e}")
        return f"Error: {e}"

def run_workflow():
    print("Starting Omni-Vertical Intel Gatherer Workflow...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"CRITICAL ERROR: Could not connect to Brave on port 9222. Ensure it's running with the CDP flag. Details: {e}")
            return

        # Map pages
        targets = {}
        for platform in PROMPTS.keys():
            page = get_page_by_url_substring(browser, platform)
            if page:
                targets[platform] = page
            else:
                print(f"WARNING: Tab for {platform} not found. Please ensure it is open.")

        if not targets:
            print("No target tabs found. Exiting.")
            return

        print(f"Found {len(targets)} / 4 tabs active.")

        # Phase 1: Injection (Grok, Perplexity, Gemini)
        researchers = ["grok.com", "perplexity.ai", "gemini.google.com"]
        for platform in researchers:
            if platform in targets:
                inject_prompt(targets[platform], platform, PROMPTS[platform])

        print("\nWaiting 45 seconds for research generation...\n")
        time.sleep(45)

        # Phase 2: Extraction
        findings = {}
        for platform in researchers:
            if platform in targets:
                findings[platform] = extract_response(targets[platform], platform)

        # Build combined string
        consolidated_findings = f"""Here are the findings from the research agents regarding the Fulton Homes Sales Concierge:

--- GROK (Unfiltered Pulse) ---
{findings.get('grok.com', 'No data collected')}

--- PERPLEXITY (Deep Researcher) ---
{findings.get('perplexity.ai', 'No data collected')}

--- GEMINI (Policy Auditor) ---
{findings.get('gemini.google.com', 'No data collected')}

Now, act as the Dojo Master and generate the ultimate, highly-refined System Prompt for this Fulton Homes 'Sales Concierge' agent."""

        # Save Raw Intel
        try:
            with open(r"C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\intel_report_raw.txt", "w", encoding="utf-8") as f:
                f.write(consolidated_findings)
            print("Raw intel saved to intel_report_raw.txt")
        except Exception as e:
            print(f"Failed to save raw intel: {e}")

        # Phase 3: Final Synthesis Injection (ChatGPT)
        if "chatgpt.com" in targets:
            print("\nInjecting synthesis prompt into ChatGPT...")
            # We copy to clipboard and paste to handle very large text reliably in UI
            page = targets["chatgpt.com"]
            page.bring_to_front()
            time.sleep(1)
            
            # Use JS to inject the massive string into clipboard, then paste
            page.evaluate("text => navigator.clipboard.writeText(text)", consolidated_findings)
            time.sleep(1)
            
            box = page.locator('#prompt-textarea')
            box.click()
            page.keyboard.press("Control+V")
            time.sleep(1)
            page.keyboard.press("Enter")

            print("Waiting 45 seconds for ChatGPT synthesis...")
            time.sleep(45)

            final_prompt = extract_response(page, "chatgpt.com")
            
            try:
                with open(r"C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\final_system_prompt.txt", "w", encoding="utf-8") as f:
                    f.write(final_prompt)
                print("\nSUCCESS! Final System Prompt saved to final_system_prompt.txt")
            except Exception as e:
                print(f"Failed to save final prompt: {e}")
        else:
            print("ChatGPT tab not found for final synthesis.")

if __name__ == "__main__":
    run_workflow()
