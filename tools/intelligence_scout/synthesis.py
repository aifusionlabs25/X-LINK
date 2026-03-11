"""
X-LINK HUB v3 — Intelligence Scout Synthesis
Ollama-powered analysis engine for Keep.md ingestion and research tasks.
Extracted from the legacy intelligence_sweeper.py.
"""

import os
import sys
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT_DIR, ".env"))
logger = logging.getLogger("scout.synthesis")

KEEP_API_KEY = os.getenv("KEEP_MD_API_KEY")
KEEP_API_BASE = "https://keep.md"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "llama3.2"

ASTRID_PROMPT = (
    "You are Astrid, the Chief of Staff. Read the following markdown data that the Founder saved via Keep.md. "
    "Write a 2-sentence executive summary of its core value, and list 1 potential business opportunity "
    "it presents for our AI agency. Output must be concise and professional."
)


def fetch_keep_item():
    """Fetch a single item from Keep.md (free tier: limit=1, content=1)."""
    url = f"{KEEP_API_BASE}/api/feed?limit=1&content=1"
    headers = {}
    if KEEP_API_KEY:
        headers["Authorization"] = f"Bearer {KEEP_API_KEY}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.error(f"Keep.md fetch failed: {response.status_code}")
            return None
        data = response.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        return items[0] if items else None
    except Exception as e:
        logger.error(f"Keep.md network error: {e}")
        return None


def analyze_with_ollama(content: str, prompt: str = None) -> str:
    """Send content to local Ollama for analysis."""
    prompt = prompt or ASTRID_PROMPT
    payload = {
        "model": MODEL,
        "prompt": f"{prompt}\n\nData:\n{content}\n\nAnalysis:\n",
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=300)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"Ollama analysis failed: {e}")
        return ""


def mark_processed(item_id: str):
    """Mark an item as processed in Keep.md."""
    url = f"{KEEP_API_BASE}/api/items/mark-processed"
    headers = {"Content-Type": "application/json"}
    if KEEP_API_KEY:
        headers["Authorization"] = f"Bearer {KEEP_API_KEY}"

    try:
        requests.post(url, headers=headers, json={"ids": [item_id]}, timeout=15)
    except Exception as e:
        logger.warning(f"Mark-processed failed: {e}")


async def run_synthesis(source: str = "keep_md", query: str = "") -> dict:
    """
    Run the intelligence synthesis pipeline.
    Returns a structured dict with title, analysis, source, and raw content.
    """
    if source == "keep_md":
        item = fetch_keep_item()
        if not item:
            return {"status": "empty", "message": "No items in Keep.md queue."}

        content = item.get("contentMarkdown", "")
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        item_id = item.get("id") or item.get("_id")

        analysis = analyze_with_ollama(content)

        if item_id:
            mark_processed(item_id)

        return {
            "status": "success",
            "title": title,
            "url": url,
            "analysis": analysis,
            "content_preview": content[:500],
            "timestamp": datetime.now().isoformat(),
        }

    else:
        return {
            "status": "unsupported",
            "message": f"Source '{source}' not yet implemented.",
        }
