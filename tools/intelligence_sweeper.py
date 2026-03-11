import os
import sys
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
import logging

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

KEEP_API_KEY = os.getenv("KEEP_MD_API_KEY")
if not KEEP_API_KEY:
    logging.warning("⚠️ KEEP_MD_API_KEY not found in environment. Please ensure it's set if authorization is required.")

KEEP_API_BASE = "https://keep.md"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "llama3.2"

def fetch_keep_item():
    url = f"{KEEP_API_BASE}/api/feed?limit=1&content=1"
    headers = {}
    if KEEP_API_KEY:
        headers["Authorization"] = f"Bearer {KEEP_API_KEY}"
    
    logging.info(f"📡 Fetching latest insight from Keep.md...")
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logging.error(f"❌ Failed to fetch Keep.md feed: {response.status_code} - {response.text}")
            return None
            
        data = response.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        
        if not items:
            logging.info("📭 No new items found in Keep.md feed.")
            return None
            
        return items[0]
    except Exception as e:
        logging.error(f"❌ Network error fetching from Keep.md: {e}")
        return None

def process_with_ollama(content):
    logging.info(f"🧠 Engaging local Ollama cognitive engine ({MODEL})...")
    system_prompt = (
        "You are Astrid, the Chief of Staff. Review this 'autoresearch' paradigm by Andrej Karpathy. "
        "Based on his 'Always-On Employee' and '5-minute test budget' principles, propose ONE specific way "
        "we can upgrade the X-Link engine to be self-improving."
    )
    
    payload = {
        "model": MODEL,
        "prompt": f"{system_prompt}\n\nKeep.md Data:\n{content}\n\nAstrid's Architecture Proposal:\n",
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=300)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        logging.error(f"❌ Ollama processing failed: {e}")
        return None

def save_strategic_proposal(item, analysis):
    vault_dir = os.path.join(ROOT_DIR, 'vault')
    os.makedirs(vault_dir, exist_ok=True)
    report_path = os.path.join(vault_dir, 'STRATEGIC_UPGRADES.md')
    
    title = item.get("title", "Karpathy Autoresearch Paradigm")
    url = item.get("url", "No URL provided")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    entry = f"# 🚀 STRATEGIC UPGRADE: {title}\n"
    entry += f"**Date:** {timestamp} | **Source:** {url}\n\n"
    entry += f"## Astrid's Architecture Proposal\n{analysis}\n\n"
    entry += "---\n\n"
    
    try:
        with open(report_path, 'a', encoding='utf-8') as f:
            f.write(entry)
        logging.info(f"💾 Strategic Architecture Proposal archived to vault/STRATEGIC_UPGRADES.md")
        return report_path
    except Exception as e:
        logging.error(f"❌ Failed to archive strategic upgrade: {e}")
        return None

def mark_item_processed(item_id):
    url = f"{KEEP_API_BASE}/api/items/mark-processed"
    headers = {"Content-Type": "application/json"}
    if KEEP_API_KEY:
        headers["Authorization"] = f"Bearer {KEEP_API_KEY}"
        
    payload = {
        "id": item_id,
        "itemIds": [item_id]
    } 
    
    logging.info(f"🧹 Marking item {item_id} as processed in Keep.md...")
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201, 204]:
            logging.info("✅ Item successfully cleared from Keep.md queue.")
        else:
            logging.warning(f"⚠️ Failed to mark processed: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"❌ Error communicating with Keep.md API during cleanup: {e}")

def notify_founder(proposal_path):
    # Log it as requested
    logging.info(f"📢 STRATEGY PAPER READY: {proposal_path}")
    
    # Optional: Discord notification if we want to be fancy, 
    # but for now we'll stick to the log as it's more reliable in this standalone script.
    # In a real scenario, we'd import a discord webhook utility.
    pass

def run_sweeper():
    logging.info("🕵️‍♀️ Astrid Sweeper Protocol initialized.")
    item = fetch_keep_item()
    if not item:
        return
        
    content = item.get("contentMarkdown")
    if not content:
        logging.warning("⚠️ Item fetched but 'contentMarkdown' is missing. Skipping.")
        return
        
    analysis = process_with_ollama(content)
    if not analysis:
        return
        
    report_path = save_strategic_proposal(item, analysis)
    
    item_id = item.get("id") or item.get("_id")
    if item_id:
        mark_item_processed(item_id)
        if report_path:
            notify_founder(report_path)
    else:
        logging.warning("⚠️ Could not extract 'id' from Keep.md item to mark it processed.")

if __name__ == "__main__":
    run_sweeper()
