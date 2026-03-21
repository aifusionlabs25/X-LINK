"""
Anam Prompt Sync v1 — AI Fusion Labs
====================================
Synchronizes agent personas and prompts from Anam Lab (lab.anam.ai) 
to the local config/agents.yaml for use in X-Agent Eval simulations.
"""

import asyncio
import os
import sys
import yaml
import json
import logging
import argparse
from datetime import datetime

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.base_tool import BaseTool
from x_link_engine import XLinkEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("anam_sync")

# Selectors identified via browser exploration
SELECTORS = {
    "persona_nav": "a[href='/personas'], li:has-text('Personas')",
    "agent_list_item": "div[role='listitem'], tr.persona-row", # Generic, will refine
    "prompt_textarea": "textarea[placeholder*='You are a helpful AI assistant']",
    "persona_input": "input[placeholder*='A warm and patient customer support specialist']",
    "prompt_tab": "button:has-text('Prompt')"
}

class AnamSyncTool:
    def __init__(self):
        self.engine = XLinkEngine()
        self.agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")

    async def sync_all(self, target_agent=None):
        """Main entry point to sync all or one agent."""
        if not await self.engine.connect():
            logger.error("❌ Failed to connect to CDP.")
            return False

        try:
            # 1. Load local agents.yaml
            with open(self.agents_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            agents = config.get("agents", [])
            if target_agent:
                agents = [a for a in agents if a["slug"] == target_agent or a["name"].lower() == target_agent.lower()]
                if not agents:
                    logger.error(f"❌ Agent '{target_agent}' not found in agents.yaml.")
                    return False

            logger.info(f"🔄 Starting Anam Sync for {len(agents)} agents...")

            # 2. Navigate directly to Personas list
            page = await self.engine.ensure_page("https://lab.anam.ai/personas", wait_sec=5)
            
            # Check for security wall
            wall = await self.engine.detect_security_wall(page)
            if wall:
                logger.warning(f"🚨 Security wall detected: {wall}. Login required.")
                return False

            for agent in agents:
                # Refresh list page for each agent to ensure clean state
                await page.goto("https://lab.anam.ai/personas")
                await asyncio.sleep(4)
                
                success = await self._sync_single_agent(page, agent)
                if success:
                    logger.info(f"✅ Synced {agent['name']}")
                else:
                    logger.warning(f"⚠️ Failed to sync {agent['name']}")

            # 3. Save updated config
            with open(self.agents_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, sort_keys=False, indent=2, allow_unicode=True)
            
            logger.info("💾 Local config/agents.yaml updated.")
            
            # Explicitly close the automation tab
            try:
                await page.close()
            except:
                pass
                
            return True

        except Exception as e:
            logger.error(f"❌ Sync failed: {e}")
            return False
        finally:
            await self.engine.close()

    async def _sync_single_agent(self, page, agent_conf):
        """Navigate to specific agent and scrape prompt."""
        try:
            # Use anam_name if provided, else fallback to name
            match_name = agent_conf.get("anam_name") or agent_conf["name"]
            logger.info(f"   Searching for persona matching: {match_name}")
            
            # 1. Wait for name to appear
            try:
                await page.wait_for_selector(f"text='{match_name}'", timeout=12000)
            except:
                logger.warning(f"   Timeout waiting for '{match_name}'.")
            
            # 2. Click the agent name
            agent_link = page.locator(f"text='{match_name}'").first
            await agent_link.click()
            await asyncio.sleep(6)

            # 3. Ensure we are on Prompt tab
            # Sometimes it loads directly, sometimes we need to click
            prompt_tab = page.locator("button:has-text('Prompt')")
            if await prompt_tab.count() > 0:
                await prompt_tab.click()
                await asyncio.sleep(2)

            # 4. Extract Persona Description (short)
            persona_desc = ""
            desc_el = page.locator(SELECTORS["persona_input"])
            if await desc_el.count() > 0:
                persona_desc = await desc_el.input_value()
            
            # 5. Extract Main Prompt / System Instructions
            prompt_el = page.locator(SELECTORS["prompt_textarea"])
            if await prompt_el.count() == 0:
                # If the specific selector fails, try a more generic one
                prompt_el = page.locator("textarea").first
                
            # VISUAL FEEDBACK: Highlight the element so the user sees the extraction
            try:
                await prompt_el.evaluate("el => { el.style.border = '4px solid #00ff00'; el.style.boxShadow = '0 0 15px #00ff00'; }")
                await asyncio.sleep(1.5) # Let the user see it
            except:
                pass
                
            system_prompt = await prompt_el.input_value()

            if not system_prompt or len(system_prompt) < 100:
                logger.error(f"   Extracted prompt is suspicious (too short or empty) for {name}")
                await page.screenshot(path=os.path.join(ROOT_DIR, "vault", f"sync_error_{name}.png"))
                return False

            # Update local config
            agent_conf["description"] = persona_desc or agent_conf.get("description", "")
            agent_conf["persona"] = system_prompt
            agent_conf["last_synced"] = datetime.now().isoformat()
            
            return True

        except Exception as e:
            logger.error(f"   Error syncing {agent_conf['name']}: {e}")
            await page.screenshot(path=os.path.join(ROOT_DIR, "vault", f"sync_exception_{agent_conf['name']}.png"))
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Anam prompts to local config.")
    parser.add_argument("--agent", help="Specific agent slug to sync")
    args = parser.parse_args()

    sync = AnamSyncTool()
    asyncio.run(sync.sync_all(target_agent=args.agent))
