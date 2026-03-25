"""
X-Agent Eval v1 — Transcript Capture (QA Text Lane)
Captures session transcripts from X-Agent website DOM using deterministic QA mode.
"""

import asyncio
import uuid
import json
import logging
import os
import sys
import re
from datetime import datetime
from typing import List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)
from tools.xagent_eval.batch_runner import recursively_redact

logger = logging.getLogger("xagent_eval.transcript_capture")

# QA Mode Selectors
SELECTORS = {
    "qa_chat_root": "[data-testid='qa-chat-root']",
    "qa_connection_state": "[data-testid='qa-connection-state']",
    "qa_transcript": "[data-testid='qa-transcript']",
    "qa_input": "[data-testid='qa-input']",
    "qa_send": "[data-testid='qa-send']",
    "qa_clear": "[data-testid='qa-clear']",
    "qa_message_user": "[data-testid='qa-message-user']",
    "qa_message_agent": "[data-testid='qa-message-agent']",
    "qa_message_system": "[data-testid='qa-message-system']"
}



def _map_domain_context(text: str, agent_domain: str) -> str:
    """Globally swaps industry keywords to match the agent's domain."""
    if not text: return text
    if "Law Firm" in agent_domain or "Legal" in agent_domain:
        # Map SaaS concepts to Legal Representation concepts
        text = text.replace("SaaS", "Legal Representation")
        text = text.replace("AI solutions", "Legal Defense")
        text = text.replace("AI agents", "Legal Specialists")
        text = text.replace("software", "legal assistance")
        text = text.replace("product", "representation")
        text = text.replace("demo", "consultation")
        text = text.replace("vendor", "firm")
        text = text.replace("subscription", "retainer")
        text = text.replace("free trial", "initial review")
    elif "Field Service" in agent_domain:
        text = text.replace("SaaS", "Field Service Platform")
        text = text.replace("AI solutions", "Operational Efficiency Tools")
        text = text.replace("software", "field dispatch system")
    return text


class LiveBrowserCapture:
    """
    Handles live browser-grounded interaction for X-Agent evaluation.
    Targets /demo/[slug]?qa=1 deterministic lane.
    """

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self.cdp_url = cdp_url
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.capture_error = None
        self.slug = None
        self.target_url = None

    async def connect(self, agent_slug: str, context: dict) -> bool:
        """Connect to existing remote browser or launch a new one."""
        try:
            from playwright.async_api import async_playwright
            self.pw = await async_playwright().start()
            
            # Use a timeout to avoid hanging if the browser is unresponsive or port is locked
            self.browser = await self.pw.chromium.connect_over_cdp(self.cdp_url, timeout=15000)
            self.context = self.browser.contexts[0]

            
            # Clean up orphaned x-agent tabs from previous crashed runs to avoid API concurrency limits
            for p in self.context.pages:
                url = p.url.lower()
                # ONLY close if it's an agent demo lane (?qa=1) or an x-agent specific URL.
                # DO NOT close the Hub (localhost:5001/hub)
                if ("x-agent" in url or "localhost" in url) and ("?qa=1" in url or "/demo/" in url):
                    try:
                        # Gracefully disconnect before forcing close, otherwise Anam backend locks the session for 2 minutes
                        end_btn = p.locator("button", has_text="End Session")
                        try:
                            if await end_btn.count() > 0 and await end_btn.is_visible(timeout=1000):
                                await end_btn.click()
                                await asyncio.sleep(2) # Allow backend disconnect
                        except Exception:
                            pass
                        await p.close()
                    except Exception:
                        pass
                        
            self.page = await self.context.new_page()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to CDP at {self.cdp_url}: {e}")
            await self.close()
            return False

    async def close(self):
        """Close playwright session."""
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.pw:
                await self.pw.stop()
        except Exception:
            pass

    async def navigate_to_agent(self, env_url: str, agent_name: str) -> bool:
        """
        Navigate directly to the QA deterministic lane for the agent.
        """
        try:
            self.slug = agent_name.lower().replace(" ", "-")
            self.target_url = f"{env_url.rstrip('/')}/demo/{self.slug}?qa=1"
            logger.info(f"Navigating to QA lane: {self.target_url}")
            
            await self.page.goto(self.target_url, wait_until="networkidle")

            # Assert QA chat root exists (Fail-fast condition)
            try:
                await self.page.wait_for_selector(SELECTORS["qa_chat_root"], state="visible", timeout=15000)
            except Exception:
                self.capture_error = "qa-chat-root never appeared"
                logger.error(self.capture_error)
                return False

            # Assert connection state reaches 'streaming'
            try:
                logger.info("Waiting for QA connection to be streaming...")
                await self.page.locator(SELECTORS["qa_connection_state"]).filter(has_text=re.compile(r"streaming", re.IGNORECASE)).wait_for(state="visible", timeout=30000)
            except Exception:
                self.capture_error = "connection state never became streaming"
                logger.error(self.capture_error)
                return False

            return True
        except Exception as e:
            self.capture_error = f"Navigation failed: {e}. Ensure Demo Server is at {self.target_url}"
            logger.error(f"❌ [DOJO_NAV_ERROR] {self.capture_error}")
            return False

    async def send_qa_message(self, message: str) -> bool:
        """Type and send a user message using QA inputs."""
        try:
            # The website frontend currently fails to remove the 'disabled' attribute natively
            # Forcefully strip the 'disabled' attribute from the DOM to allow Playwright to type
            await self.page.evaluate(f'''() => {{
                try {{
                    const inputEl = document.querySelector("{SELECTORS['qa_input']}");
                    const sendEl = document.querySelector("{SELECTORS['qa_send']}");
                    if (inputEl) inputEl.removeAttribute("disabled");
                    if (sendEl) sendEl.removeAttribute("disabled");
                }} catch (e) {{}}
            }}''')
            
            # Force the fill even if Playwright thinks it's un-actionable
            await self.page.fill(SELECTORS["qa_input"], message, force=True)
            await asyncio.sleep(0.2) # Brief pause for react state
            
            # Force click the send button
            await self.page.click(SELECTORS["qa_send"], force=True)
            return True
        except Exception as e:
            self.capture_error = f"Failed to send message: {e}"
            logger.error(self.capture_error)
            return False

    async def wait_for_agent_turn_start(self, prev_agent_count: int, timeout: int = 60) -> bool:
        """Wait until the agent starts responding (first visible token)."""
        logger.info(f"Waiting for agent turn start (prev={prev_agent_count}, timeout={timeout}s)...")
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # Check for system/error messages
            sys_loc = self.page.locator(SELECTORS["qa_message_system"])
            sys_count = await sys_loc.count()
            for i in range(sys_count):
                text = await sys_loc.nth(i).inner_text()
                # These are known noise messages - they don't count as responses OR as errors
                if any(ok in text for ok in ["Initializing", "Neural Link", "Reconnecting", "Connected", "Disconnecting", "Disconnected", "Neural Link Established"]):
                    continue
                # If we get here, it's a real terminal error (e.g. "WebSocket Error", "Session Expired")
                self.capture_error = f"a system/error message appeared: {text}"
                logger.error(self.capture_error)
                return False
                
            agent_msgs = await self.page.locator(SELECTORS["qa_message_agent"]).count()
            if agent_msgs > prev_agent_count:
                logger.info(f"Agent turn start detected (turn {agent_msgs}).")
                return True
                
            await asyncio.sleep(1.0)
            
        self.capture_error = f"agent never started responding within {timeout}s"
        logger.error(self.capture_error)
        return False

    async def wait_for_agent_turn_complete(self, stable_seconds: float = 4.0, min_floor: float = 5.0, timeout: int = 45) -> bool:
        """
        Polls DOM until agent text stops changing for 'stable_seconds' seconds.
        Floor ensures we don't snap-capture a partial 'thinking' state.
        """
        logger.info(f"Waiting for agent turn completion (stability={stable_seconds}s, floor={min_floor}s)...")
        start_time = asyncio.get_event_loop().time()
        last_text = ""
        last_change_count = 0
        last_change_time = start_time
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # 1. Capture current agent text (the last message block)
            agent_loc = self.page.locator(SELECTORS["qa_message_agent"]).last
            if await agent_loc.count() == 0:
                await asyncio.sleep(0.5)
                continue
                
            current_text = await agent_loc.inner_text()
            current_time = asyncio.get_event_loop().time()
            
            # 2. Check for changes
            if current_text != last_text:
                last_text = current_text
                last_change_time = current_time
                logger.debug(f"Agent text changed: {len(current_text)} chars")
            
            # 3. Check stability and floor
            elapsed_since_start = current_time - start_time
            elapsed_since_change = current_time - last_change_time
            
            # Completion criteria:
            # - Text is non-empty
            # - Text hasn't changed for stable_seconds
            # - Minimum turn floor has elapsed
            if elapsed_since_start >= min_floor and elapsed_since_change >= stable_seconds and len(last_text.strip()) > 0:
                logger.info(f"Agent turn complete detection. Final length: {len(last_text)}")
                return True
                
            await asyncio.sleep(0.5)
            
        self.capture_error = "agent response never stabilized within timeout"
        logger.error(self.capture_error)
        return False

    async def export_qa_transcript(self) -> List[dict]:
        """Extract all messages from the DOM deterministically."""
        turns = []
        try:
            raw_msgs = await self.page.evaluate('''() => {
                const els = document.querySelectorAll('[data-testid="qa-message-user"], [data-testid="qa-message-agent"], [data-testid="qa-message-system"]');
                return Array.from(els).map(el => ({
                    text: el.innerText,
                    test_id: el.getAttribute("data-testid")
                }));
            }''')
            
            for i, msg in enumerate(raw_msgs):
                test_id = msg.get("test_id")
                speaker = "system"
                if test_id == "qa-message-user":
                    speaker = "test_user"
                elif test_id == "qa-message-agent":
                    speaker = "agent_under_test"
                
                text = msg.get("text", "").strip()
                if not text:
                    continue
                    
                turns.append({
                    "turn": len(turns) + 1,
                    "speaker": speaker,
                    "text": text,
                    "timestamp": datetime.now().isoformat()
                })
        except Exception as e:
            logger.error(f"Failed to export QA transcript: {e}")
        return turns

    async def run_session(
        self,
        scenario: dict,
        max_turns: int,
        inputs: dict,
        run_id: str,
        batch_id: str,
    ) -> List[dict]:
        """
        Orchestrates the live QA session loop with Agent-First support and explicit completion reasoning.
        """
        transcript = []
        status = "pending"
        fail_reason = None
        error_code = None
        completion_reason = "pending"

        try:
            await asyncio.sleep(2) # Initial stabilization

            # Update active_session.json with current run_id
            try:
                session_path = os.path.join(ROOT_DIR, "vault", "evals", "active_session.json")
                if os.path.exists(session_path):
                    with open(session_path, "r", encoding="utf-8") as f:
                        session_data = json.load(f)
                    session_data["current_run_id"] = run_id
                    with open(session_path, "w", encoding="utf-8") as f:
                        json.dump(session_data, f)
            except: pass

            # ── STATE: SESSION_STARTED -> WAITING_FOR_AGENT_OPENING ──
            # The agent is configured to proactive opening. 
            logger.info(f"[{run_id}] Startup: Waiting for agent proactive opening turn...")
            
            # Check if there's already an opening turn
            agent_msgs_start = await self.page.locator(SELECTORS["qa_message_agent"]).count()
            
            # WAITING_FOR_AGENT_OPENING
            if agent_msgs_start == 0:
                started = await self.wait_for_agent_turn_start(0, timeout=45) # Longer for cold start
                if not started:
                    # Some agents don't open proactively; we handle as failure or fallback
                    logger.warning(f"[{run_id}] Agent did not open proactively within 45s. Forcing user opening.")
                    user_msg = scenario.get("opening_message", "Hello.")
                    
                    # Domain Pivot for forced opening
                    agent_slug = inputs.get("target_agent", "unknown")
                    try:
                        import yaml
                        agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
                        with open(agents_path, "r", encoding="utf-8") as f:
                            agents_data = yaml.safe_load(f)
                        agent_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == agent_slug), {})
                        agent_domain = agent_conf.get("domain", "SaaS / AI")
                        user_msg = _map_domain_context(user_msg, agent_domain)
                        logger.info(f"Opening message mapped for {agent_slug} in browser mode.")
                    except: pass
                else:
                    # WAITING_FOR_AGENT_OPENING_COMPLETE
                    completed = await self.wait_for_agent_turn_complete(stable_seconds=3.0, min_floor=4.0)
                    if not completed:
                        logger.warning(f"[{run_id}] Opening turn failed to stabilize.")
                    user_msg = None # We will generate the first user response below
            else:
                # Agent already spoke (e.g. fast load)
                await self.wait_for_agent_turn_complete(stable_seconds=3.0, min_floor=4.0)
                user_msg = None

            # ── MAIN LOOP ──
            twists = {tw.get("turn", 0): tw.get("injection", "") for tw in scenario.get("twists", [])}

            import aiohttp
            async with aiohttp.ClientSession() as session:
                for turn_idx in range(1, max_turns + 1):
                    
                    # IF we don't have a user message (because agent spoke first), generate one
                    if user_msg is None:
                        current_turns = await self.export_qa_transcript()
                        user_msg = await self._generate_simulated_user_reply(session, current_turns, scenario, inputs)

                    # Fetch twists
                    if turn_idx in twists and turn_idx > 1:
                        user_msg = twists[turn_idx]

                    # STATE: USER_TURN_READY -> USER_MESSAGE_SENT
                    agent_count_before = await self.page.locator(SELECTORS["qa_message_agent"]).count()
                    logger.info(f"[{run_id}] Turn {turn_idx} | User sending: {user_msg}")
                    
                    success = await self.send_qa_message(user_msg)
                    await self._write_telemetry(run_id, batch_id, turn_idx, "USER_MESSAGE_SENT", await self.export_qa_transcript(), status="running")
                    if not success:
                        status = "failed"
                        fail_reason = self.capture_error or "send QA message failed"
                        completion_reason = "transcript_failed"
                        break

                    # STATE: WAITING_FOR_AGENT_START
                    started = await self.wait_for_agent_turn_start(agent_count_before)
                    await self._write_telemetry(run_id, batch_id, turn_idx, "AGENT_RESPONDING", await self.export_qa_transcript(), status="running")
                    if not started:
                        status = "failed"
                        fail_reason = self.capture_error or "agent reply timeout"
                        completion_reason = "agent_stalled"
                        break

                    # STATE: WAITING_FOR_AGENT_FINISH
                    completed = await self.wait_for_agent_turn_complete(stable_seconds=3.0, min_floor=4.0)
                    await self._write_telemetry(run_id, batch_id, turn_idx, "AGENT_TURN_COMPLETE", await self.export_qa_transcript(), status="running")
                    if not completed:
                        status = "partial"
                        fail_reason = self.capture_error or "agent response cutoff"
                        error_code = "E_AGENT_RESPONSE_CUTOFF"
                        completion_reason = "response_cutoff"
                        # Capture screenshot on cutoff
                        cutoff_screenshot = os.path.join(ROOT_DIR, "vault", "evals", "artifacts", f"cutoff_{run_id}_t{turn_idx}.png")
                        try:
                            await self.page.screenshot(path=cutoff_screenshot)
                            logger.warning(f"Turn cutoff detected! Screenshot saved: {cutoff_screenshot}")
                        except: pass
                        break

                    # STATE: AGENT_TURN_COMPLETE -> NEXT_USER_TURN_ALLOWED
                    await asyncio.sleep(0.5)

                    # ── EXPLICIT COMPLETION CHECK ──
                    current_turns = await self.export_qa_transcript()
                    is_complete, reason = self._check_scenario_completion(current_turns, scenario, turn_idx, max_turns)
                    
                    if is_complete:
                        status = "complete"
                        completion_reason = reason
                        logger.info(f"[{run_id}] Scenario complete triggered: {reason}")
                        await self._write_telemetry(run_id, batch_id, turn_idx, "COMPLETE", current_turns, status=status, reason=reason)
                        break

                    # Prepare for next turn
                    user_msg = await self._generate_simulated_user_reply(session, current_turns, scenario, inputs)

            if status == "pending":
                status = "complete"
                completion_reason = "max_turns_reached"

        except Exception as e:
            logger.error(f"Live QA session execution failed: {e}")
            status = "failed"
            fail_reason = str(e)
            completion_reason = "transcript_failed"
            
        # Final Transcript Extraction
        transcript = await self.export_qa_transcript()
        
        # Take screenshot
        screenshot_path = os.path.join(ROOT_DIR, "vault", "evals", "artifacts", f"screenshot_{run_id}.png")
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        try:
            await self.page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            screenshot_path = None
            
        final_agent_reply = "None"
        for t in reversed(transcript):
            if t["speaker"] == "agent_under_test":
                final_agent_reply = t["text"]
                break

        # Enrich transcript with required metadata for downstream assertions
        for turn in transcript:
            self._enrich_turn(turn, inputs, scenario, run_id, batch_id, "live_browser_qa")
            turn["transcript_status"] = status
            turn["fail_reason"] = fail_reason
            turn["error_code"] = error_code
            turn["completion_reason"] = completion_reason
            turn["slug"] = self.slug
            turn["url"] = self.target_url
            turn["screenshot_path"] = screenshot_path
            turn["final_agent_reply"] = final_agent_reply

        return transcript

    async def _write_telemetry(self, run_id: str, batch_id: str, turn: int, state: str, transcript: List[dict], status: str = "running", reason: str = None, error: str = None):
        """Write live telemetry for Hub polling."""
        try:
            p = os.path.join(ROOT_DIR, "vault", "evals", "runs", run_id)
            os.makedirs(p, exist_ok=True)
            tel_path = os.path.join(p, "live_telemetry.json")
            data = {
                "run_id": run_id,
                "batch_id": batch_id,
                "turn": turn,
                "state": state,
                "status": status,
                "reason": reason,
                "error": error,
                "actual_turns": len(transcript),
                "transcript": recursively_redact(transcript[-10:]), # Last 10 turns for the live view
                "timestamp": datetime.now().isoformat()
            }
            with open(tel_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to write telemetry: {e}")

    def _check_scenario_completion(self, transcript: List[dict], scenario: dict, turn_idx: int, max_turns: int) -> tuple:
        """Determines if the conversation should end based on objective completion."""
        # Defaults
        min_turns = scenario.get("min_turns", 4)
        
        # 1. Turn count floor
        if turn_idx < min_turns:
            return False, "too_brief"

        # 2. Heuristic check: Did the agent answer the core need?
        # In V1, we check if the last agent response is substantial and seems like a closure
        last_turn = transcript[-1] if transcript else {}
        text = last_turn.get("text", "").lower()
        
        # Simple closure keywords
        closure_signals = ["goodbye", "have a great day", "let me know", "looking forward", "calendar", "sent you an email"]
        
        # If we reached target turns and have a closure signal
        if turn_idx >= min_turns and any(sig in text for sig in closure_signals):
            return True, "scenario_complete"

        # 3. Handle max turns (the loop handles this, but we can signal it here)
        if turn_idx >= max_turns:
            return True, "max_turns_reached"

        return False, "pending"

    def _enrich_turn(self, turn: dict, inputs: dict, scenario: dict, run_id: str, batch_id: str, source: str):
        """Add provenance fields to a transcript turn."""
        turn.update({
            "target_agent": inputs.get("target_agent"),
            "environment": inputs.get("environment"),
            "scenario_pack": inputs.get("scenario_pack"),
            "scenario_id": scenario.get("scenario_id"),
            "run_id": run_id,
            "batch_id": batch_id,
            "capture_source": source,
        })

    async def _generate_simulated_user_reply(self, session, transcript: List[dict], scenario: dict, inputs: dict) -> str:
        """Use Ollama to generate a contextual user reply for the live session."""
        OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

        # Load agent context
        agent_slug = inputs.get("target_agent", "unknown")
        agent_role_text = "AI Agent"
        agent_desc = ""
        try:
            import yaml
            agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
            with open(agents_path, "r", encoding="utf-8") as f:
                agents_data = yaml.safe_load(f)
            agent_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == agent_slug), {})
            agent_role_text = agent_conf.get("role", "AI Agent")
            agent_desc = agent_conf.get("description", "")
        except Exception as e:
            logger.warning(f"Failed to load agent role: {e}")

        user_profile = scenario.get("user_profile", {})
        user_name = user_profile.get("name", "Arthur")
        user_context_base = user_profile.get("context", "A prospect visiting the website.")
        user_role = scenario.get("role", "cooperative_user")
        
        # Pre-process user context and scenario goal
        agent_domain = agent_conf.get("domain", "SaaS / AI")
        user_context_base = _map_domain_context(user_profile.get("context", "A prospect visiting the website."), agent_domain)
        scenario_goal = _map_domain_context(scenario.get("goal", ""), agent_domain)
        
        # Override user context slightly if they are talking to a specific agent, to avoid generic AI SaaS queries
        user_context = f"{user_context_base} You are currently talking to an agent acting as: {agent_role_text} in the {agent_domain} domain. {agent_desc}"

        # Filter out system turns and clean up agent text
        filtered_transcript = []
        for t in transcript:
            if t['speaker'] == 'system':
                continue
            
            text = t['text']
            if t['speaker'] == 'agent_under_test' and text.startswith("AGENT\n"):
                text = text.replace("AGENT\n", "", 1).strip()
            
            filtered_transcript.append({
                "speaker": t['speaker'],
                "text": text
            })

        name_map = {
            "agent_under_test": "Agent",
            "test_user": user_name
        }

        conv_lines = [f"{name_map.get(t['speaker'], t['speaker'])}: {t['text']}" for t in filtered_transcript[-6:]]
        conv_text = "\n".join(conv_lines)

        scenario_goal = scenario.get("objective", f"Engage with the {agent_role_text} to resolve your inquiry.")
        scenario_desc = scenario.get("description", "")

        prompt = (
            f"### [SIMULATION SCENARIO]\n"
            f"Scenario: {scenario.get('title', 'General Interaction')}\n"
            f"Target Agent Role: {agent_role_text}\n"
            f"Objective: {scenario_goal}\n"
            f"Context: {scenario_desc}\n\n"
            f"### [USER PERSONA]\n"
            f"Name: {user_name}\n"
            f"Role/Identity: {user_context}\n"
            f"Current Mood/Tone: {user_role}\n\n"
            f"### [INSTRUCTIONS]\n"
            f"1. You are {user_name}. Stay in character. Respond naturally but dismiss any 'Neural Link' or 'System' metadata.\n"
            f"2. Keep your response concise (1-2 sentences).\n"
            f"3. Focus on achieving your objective: {scenario_goal}. Keep your questions RELEVANT to the Target Agent Role ({agent_role_text}) and Domain ({agent_domain}).\n"
            f"4. Be realistic. If the agent is helpful, be cooperative. If angry, show it.\n\n"
            f"### [CONVERSATION HISTORY]\n"
            f"{conv_text}\n\n"
            f"{user_name}:"
        )

        try:
            async with session.post(OLLAMA_URL, json={
                "model": "qwen3-coder-next",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.8,
                    "stop": ["Agent:", "\n\n", f"{user_name}:"]
                },
            }, timeout=45) as response:
                if response.status == 200:
                    resp_json = await response.json()
                    reply = resp_json.get("response", "").strip()
                    if reply:
                        if reply.startswith(f"{user_name}:"):
                            reply = reply.replace(f"{user_name}:", "").strip()
                        return reply
                
                return f"Can you tell me more about your services as a {agent_role_text}?"
        except Exception as e:
            logger.error(f"Simulated response failed: {e}")
            return f"I need some assistance from a {agent_role_text}."
