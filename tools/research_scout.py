import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from urllib.parse import urlparse

import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine
from tools.sloane_runtime import generate_sloane_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "aratan/qwen3.5-agent-multimodal:9b"
HUB_URL = "http://localhost:5001/hub/index.html"


def process_with_ollama(content: str):
    logging.info("Engaging local Ollama cognitive engine (%s)...", MODEL)
    system_prompt = (
        "You are Sloane, the Chief of Staff. Review the following research findings and propose "
        "one specific architecture recommendation for X-LINK. Keep it concise and operational."
    )

    payload = {
        "model": MODEL,
        "prompt": f"{system_prompt}\n\nResearch Data:\n{content}\n\nSloane's Recommendation:\n",
        "stream": False,
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=300)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as exc:
        logging.error("Ollama processing failed: %s", exc)
        return None


async def run_pro_research(query: str):
    engine = XLinkEngine()
    logging.info("Initiating Pro Research Deep Dive: %s", query)

    if not await engine.connect():
        return "Browser connection failed."

    try:
        page = await engine.ensure_page("https://perplexity.ai", wait_sec=5, reuse_existing=False)

        try:
            new_btn = page.locator("button:has-text('New Thread'), a:has-text('New')").first
            if await new_btn.count() > 0:
                await new_btn.click()
                await asyncio.sleep(2)
            else:
                await page.goto("https://perplexity.ai", wait_until="networkidle")
        except Exception:
            pass

        pro_toggle = page.locator("button:has-text('Pro')").first
        if await pro_toggle.count() > 0:
            try:
                model_btn = page.locator("button:has-text('Model')").first
                if await model_btn.count() == 0:
                    await pro_toggle.click()
                    logging.info("[PRO-SEARCH] Enabled deep reasoning mode.")
                    await asyncio.sleep(2)
            except Exception:
                pass

        textarea = page.locator("#ask-input, [role='textbox'], textarea").first
        await textarea.hover()
        await textarea.click()
        await textarea.fill(query)
        await asyncio.sleep(1)
        await page.keyboard.press("Enter")

        logging.info("[PRO-SEARCH] Query submitted. Waiting for deep search...")
        await asyncio.sleep(60)

        create_page_btn = page.locator("button:has-text('Create Page')").first
        if await create_page_btn.count() > 0:
            logging.info("[PAGES] Structured report option detected.")
            await create_page_btn.click()
            await asyncio.sleep(5)

        content_el = page.locator("div.prose").first
        if await content_el.count() == 0:
            content_el = page.locator("body").first

        full_text = await content_el.inner_text()
        synthesis = process_with_ollama(full_text)

        report_dir = os.path.join(ROOT_DIR, "vault", "intel")
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(report_dir, f"PRO_RESEARCH_{timestamp}.md")

        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(f"# Pro Research: {query}\n\n")
            fh.write(f"**Source URL:** {page.url}\n\n")
            fh.write(f"## Strategic Synthesis\n{synthesis or 'Synthesis failed'}\n\n")
            fh.write(f"## Raw Intelligence\n{full_text}\n")

        logging.info("Deep research archived: %s", report_path)
        return f"Pro Research Complete: {report_path}"
    except Exception as exc:
        logging.error("Pro research failed: %s", exc)
        return f"Research error: {str(exc)}"
    finally:
        await engine.close()


async def run_trinity_search(query: str, context_block: str = ""):
    engine = XLinkEngine()
    logging.info("Initializing multi-model sweep for query: %s", query)

    if not await engine.connect():
        logging.error("Failed to connect to Brave browser via CDP.")
        return "Browser connection failed."

    targets = {
        "chatgpt.com": "https://chatgpt.com/",
        "perplexity.ai": "https://perplexity.ai/",
        "gemini.google.com": "https://gemini.google.com/app",
        "grok.com": "https://grok.com/",
    }

    pages = {}
    findings = {}

    try:
        for domain, url in targets.items():
            page = await engine.ensure_page(
                url,
                wait_sec=4,
                bring_to_front=True,
                reuse_existing=False,
                verify_session=True,
            )
            await _reset_provider_session(page, domain)
            pages[domain] = page

        for domain, page in pages.items():
            findings[domain] = await _run_provider_sweep(engine, page, domain, query, context_block=context_block)

        return _format_multi_model_findings(findings)
    except Exception as exc:
        logging.error("Multi-model sweep failed: %s", exc)
        return f"Multi-model research error: {str(exc)}"
    finally:
        for page in pages.values():
            try:
                await page.close()
            except Exception:
                pass
        try:
            await engine.ensure_page(HUB_URL, wait_sec=1, bring_to_front=True, reuse_existing=True, verify_session=False)
        except Exception:
            pass
        await engine.close()


async def _reset_provider_session(page, domain: str):
    await asyncio.sleep(1)

    if "chatgpt.com" in domain:
        selectors = [
            "a:has-text('New chat')",
            "button:has-text('New chat')",
            "[data-testid='create-new-chat-button']",
        ]
    elif "perplexity.ai" in domain:
        selectors = [
            "button:has-text('New Thread')",
            "a:has-text('New Thread')",
            "button:has-text('New')",
        ]
    elif "gemini.google.com" in domain:
        selectors = [
            "button:has-text('New chat')",
            "a:has-text('New chat')",
            "[aria-label*='New chat']",
        ]
    elif "grok.com" in domain:
        selectors = [
            "button:has-text('New chat')",
            "a:has-text('New chat')",
            "button:has-text('New conversation')",
            "[aria-label*='New chat']",
        ]
    else:
        selectors = []

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                await locator.click()
                await asyncio.sleep(2)
                return
        except Exception:
            continue


async def _run_provider_sweep(engine: XLinkEngine, page, domain: str, query: str, context_block: str = "") -> str:
    prompt = (
        "Provide a concise operator-grade answer to this research question. "
        "Prefer concrete recommendations, tradeoffs, and current best practices.\n\n"
        f"Question: {query}"
    )
    if context_block:
        prompt = f"{prompt}\n\n{context_block}"

    await engine._inject(page, domain, prompt)
    await asyncio.sleep(5)

    last_length = -1
    stable_for = 0
    deadline = asyncio.get_event_loop().time() + 180
    latest_text = ""
    while asyncio.get_event_loop().time() < deadline:
        latest_text = await engine._extract(page, domain)
        current_length = len(latest_text or "")
        if current_length > 50 and current_length == last_length:
            stable_for += 1
        else:
            stable_for = 0
            last_length = current_length
        if stable_for >= 5:
            break
        await asyncio.sleep(1)

    return latest_text or "No response found."


def _format_multi_model_findings(findings: dict[str, str]) -> str:
    sections = []
    for domain, text in findings.items():
        title = urlparse(f"https://{domain}").netloc.upper()
        sections.append(f"--- {title} ---\n{text}")
    return "\n\n".join(sections)


def synthesize_with_hermes(query: str, trinity_result: str, context_block: str = ""):
    base_persona = (
        "You are Sloane, Chief of Staff to the Founder at AI Fusion Labs. "
        "You turn messy research into crisp operator guidance. "
        "Be concise, concrete, and honest about uncertainty."
    )
    grounding_block = (
        "[RESEARCH TASK]\n"
        f"Founder query: {query}\n\n"
    )
    if context_block:
        grounding_block += f"{context_block}\n\n"
    grounding_block += (
        "[TRINITY SYNTHESIS]\n"
        f"{trinity_result}\n\n"
        "[OUTPUT FORMAT]\n"
        "Return exactly these sections in plain text:\n"
        "Executive Summary:\n"
        "Agreement:\n"
        "Tension:\n"
        "Recommended Move:\n"
        "Why It Matters:\n"
    )
    response = generate_sloane_response(
        base_persona=base_persona,
        chat_history=[{"role": "user", "content": f"Turn this Trinity research into an operator brief for: {query}"}],
        grounding_block=grounding_block,
        target_name="Sloane",
    )
    return response


async def run_multi_model_research(query: str, context_block: str = ""):
    trinity_result = await run_trinity_search(query, context_block=context_block)
    hermes_response = synthesize_with_hermes(query, trinity_result, context_block=context_block)

    report_dir = os.path.join(ROOT_DIR, "vault", "intel")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"MULTI_MODEL_RESEARCH_{timestamp}.md")

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Multi-Model Research: {query}\n\n")
        fh.write(f"**Generated:** {datetime.now().isoformat()}\n")
        fh.write(f"**Synthesis Provider:** {hermes_response.get('provider', 'unknown')}\n")
        fh.write(f"**Synthesis Model:** {hermes_response.get('model', 'unknown')}\n\n")
        if context_block:
            fh.write("## Uploaded Context\n")
            fh.write(f"{context_block}\n\n")
        fh.write("## Hermes Brief\n")
        fh.write(f"{hermes_response.get('text') or 'No Hermes brief returned.'}\n\n")
        fh.write("## Trinity Output\n")
        fh.write(f"{trinity_result}\n")

    return {
        "query": query,
        "trinity_result": trinity_result,
        "hermes_brief": hermes_response.get("text") or "",
        "synthesis_provider": hermes_response.get("provider"),
        "synthesis_model": hermes_response.get("model"),
        "report_path": report_path,
    }


async def main():
    parser = argparse.ArgumentParser(description="X-LINK research utility")
    parser.add_argument("--query", required=True, help="Run a research search with this query")
    parser.add_argument("--mode", choices=["trinity", "research"], default="trinity", help="Research mode")
    args = parser.parse_args()

    if args.mode == "research":
        logging.info("Pro Research Mode: %s", args.query)
        result = await run_pro_research(args.query)
        print(f"\n--- RESEARCH REPORT ---\n{result}\n")
        return

    logging.info("Trinity Search Mode: %s", args.query)
    result = await run_trinity_search(args.query)
    print(f"\n--- TRINITY SYNTHESIS ---\n{result}\n")

    report_dir = os.path.join(ROOT_DIR, "vault", "intel")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"TRINITY_{timestamp}.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Trinity Synthesis: {args.query}\n\n{result}\n")
    logging.info("Trinity report archived: %s", report_path)


if __name__ == "__main__":
    asyncio.run(main())
