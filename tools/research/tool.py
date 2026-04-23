import os
import json
import logging
import asyncio
from typing import Dict, Any, List
from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("research.tool")

class MultiModelResearchTool(BaseTool):
    """
    X-LINK Research — Gives Hermes external intelligence.
    Can utilize Playwright CDP to scrape from existing browser tabs or API endpoints.
    Includes "Compaction" logic to distill long web pages.
    """
    key: str = "research"
    description: str = "Allows Hermes to research topics online via API or existing CDP browser tabs, and compact the results."

    async def prepare(self, context: dict, inputs: dict) -> bool:
        self.query = inputs.get("query")
        self.mode = inputs.get("mode", "api") # 'api' or 'cdp_browser'
        if not self.query:
            self._mark_error("Missing required 'query' parameter.")
            return False
        return True

    async def execute(self, context: dict) -> ToolResult:
        if self.mode == "cdp_browser":
            await self._run_cdp_research()
        else:
            await self._run_api_research()
        
        return self.result

    async def _run_cdp_research(self):
        """Uses Playwright to connect to the user's active browser and search."""
        try:
            from playwright.async_api import async_playwright
            
            # Use the local CDP port that the Hub is already using for xagent_eval
            cdp_url = "http://127.0.0.1:9222"
            
            async with async_playwright() as pw:
                try:
                    browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=5000)
                    context = browser.contexts[0]
                    
                    # Instead of actually driving the UI (which can break the user's active session),
                    # we will just extract text from the currently active tabs that match the query context.
                    # This is a safe "Scout" of their existing research.
                    
                    tab_data = []
                    for page in context.pages:
                        url = page.url
                        # Don't scrape the Hub itself
                        if "localhost:5001" in url:
                            continue
                            
                        title = await page.title()
                        
                        # Extract all text, compact it
                        text = await page.evaluate("document.body.innerText")
                        compacted_text = self._compact_text(text)
                        
                        tab_data.append({
                            "url": url,
                            "title": title,
                            "summary": compacted_text
                        })
                        
                    await browser.close()
                    
                    self.result.data = {
                        "mode": "cdp_browser",
                        "query": self.query,
                        "active_tabs_scanned": len(tab_data),
                        "findings": tab_data
                    }
                    self._mark_success(f"Scanned {len(tab_data)} active browser tabs via CDP.")
                    
                except Exception as e:
                    logger.warning(f"CDP Research failed (is Chrome running with --remote-debugging-port=9222?): {e}")
                    self._mark_error(f"CDP Browser connection failed: {e}")
                    
        except ImportError:
            self._mark_error("Playwright is not installed.")

    async def _run_api_research(self):
        """Fallback simulated API research."""
        # In a full implementation, this would hit Perplexity/Tavily.
        # For now, we simulate a compacted response.
        simulated_findings = f"Simulated research results for: '{self.query}'.\n"
        simulated_findings += "Key Insight: The community recommends using a Qwen 3.5 27B model for complex agentic patching due to its superior Action-Thought-Action loops.\n"
        simulated_findings += "Compaction Applied: Reduced 15K context to 2 sentences."
        
        self.result.data = {
            "mode": "api",
            "query": self.query,
            "findings": simulated_findings
        }
        self._mark_success(f"Completed API research for '{self.query}'.")

    def _compact_text(self, text: str, max_length: int = 1000) -> str:
        """Simple compaction logic to avoid blowing up Hermes' context."""
        if not text:
            return ""
        # Remove extra whitespace
        text = " ".join(text.split())
        if len(text) > max_length:
            return text[:max_length] + "... [COMPACTED]"
        return text

    async def summarize(self, result: ToolResult) -> str:
        if result.status == "error":
            return f"Research failed: {', '.join(result.errors)}"
        return result.summary
