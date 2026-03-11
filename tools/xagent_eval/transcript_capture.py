"""
X-Agent Eval v1 — Transcript Capture
Captures session transcripts from X-Agent website DOM.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

logger = logging.getLogger("xagent_eval.transcript_capture")

# Known chat DOM selectors for X-Agent websites
SELECTORS = {
    "chat_container": [
        "[data-testid='chat-messages']",
        ".chat-messages",
        "#chat-container",
        ".anam-transcript",
        ".transcript-panel",
    ],
    "message_bubble": [
        "[data-testid='message']",
        ".message",
        ".chat-bubble",
        ".transcript-turn",
    ],
    "message_text": [
        "[data-testid='message-text']",
        ".message-text",
        ".bubble-content",
        "p",
    ],
    "agent_indicator": [
        ".agent-message",
        ".bot-message",
        "[data-role='assistant']",
        "[data-sender='agent']",
    ],
    "user_indicator": [
        ".user-message",
        ".human-message",
        "[data-role='user']",
        "[data-sender='user']",
    ],
    "chat_input": [
        "input[type='text']",
        "textarea",
        "[data-testid='chat-input']",
        ".chat-input input",
        "#user-input",
    ],
    "send_button": [
        "button[type='submit']",
        "[data-testid='send-button']",
        ".send-btn",
        "#send-btn",
    ],
}


async def find_selector(page, selector_list: list) -> Optional[str]:
    """Try a list of selectors and return the first that matches."""
    for sel in selector_list:
        try:
            el = await page.query_selector(sel)
            if el:
                return sel
        except Exception:
            continue
    return None


async def inject_user_message(page, message: str, retries: int = 3) -> bool:
    """Type and send a user message into the chat interface."""
    for attempt in range(retries):
        try:
            input_sel = await find_selector(page, SELECTORS["chat_input"])
            if not input_sel:
                logger.warning(f"Chat input not found (attempt {attempt + 1})")
                await asyncio.sleep(2)
                continue

            # Clear and type
            el = await page.query_selector(input_sel)
            await el.click()
            await el.fill("")
            await el.type(message, delay=30)
            await asyncio.sleep(0.5)

            # Try send button
            send_sel = await find_selector(page, SELECTORS["send_button"])
            if send_sel:
                await page.click(send_sel)
            else:
                await page.keyboard.press("Enter")

            await asyncio.sleep(1)
            return True

        except Exception as e:
            logger.warning(f"Inject message attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)

    return False


async def wait_for_agent_reply(page, prev_count: int, timeout: int = 30) -> bool:
    """Wait until a new agent message appears in the DOM."""
    msg_sel = await find_selector(page, SELECTORS["message_bubble"])
    if not msg_sel:
        return False

    for _ in range(timeout):
        messages = await page.query_selector_all(msg_sel)
        if len(messages) > prev_count:
            return True
        await asyncio.sleep(1)

    return False


async def extract_transcript(page) -> List[dict]:
    """Extract all messages from the chat DOM."""
    turns = []

    msg_sel = await find_selector(page, SELECTORS["message_bubble"])
    if not msg_sel:
        logger.warning("No message selector found in DOM.")
        return turns

    agent_sel = await find_selector(page, SELECTORS["agent_indicator"])
    user_sel = await find_selector(page, SELECTORS["user_indicator"])

    messages = await page.query_selector_all(msg_sel)

    for i, msg in enumerate(messages):
        try:
            text = await msg.inner_text()
            text = text.strip()
            if not text:
                continue

            # Determine speaker
            classes = await msg.get_attribute("class") or ""
            data_role = await msg.get_attribute("data-role") or ""
            data_sender = await msg.get_attribute("data-sender") or ""

            if any(indicator in classes for indicator in ["user", "human"]) or \
               data_role == "user" or data_sender == "user":
                speaker = "test_user"
            elif any(indicator in classes for indicator in ["agent", "bot", "assistant"]) or \
                 data_role == "assistant" or data_sender == "agent":
                speaker = "agent_under_test"
            else:
                # Heuristic: odd turns are agent (agent speaks first)
                speaker = "agent_under_test" if i % 2 == 0 else "test_user"

            turns.append({
                "turn": len(turns) + 1,
                "speaker": speaker,
                "text": text,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.warning(f"Failed to extract message {i}: {e}")

    return turns


async def capture_screenshot(page, save_path: str) -> Optional[str]:
    """Capture a screenshot of the current page state."""
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        await page.screenshot(path=save_path, full_page=True)
        return save_path
    except Exception as e:
        logger.warning(f"Screenshot capture failed: {e}")
        return None
