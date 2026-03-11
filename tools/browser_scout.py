import asyncio
import logging
import os
import sys
import argparse
from datetime import datetime

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def scout_url(url, output_path=None):
    """
    Visits a URL, scrapes text, and saves it to the vault.
    """
    engine = XLinkEngine()
    logging.info(f"🕵️‍♀️ Scouting URL: {url}")
    
    if not await engine.connect():
        return "Failed to connect to browser."

    try:
        page = await engine.ensure_page(url, wait_sec=10)
        
        # Extract title and main text
        title = await page.title()
        # Simple extraction of visible text
        content = await page.evaluate("() => document.body.innerText")
        
        # Clean up text (limit to first 10k chars for Ollama safety)
        summary_content = content[:10000]
        
        report = {
            "url": url,
            "title": title,
            "timestamp": datetime.now().isoformat(),
            "content_snippet": summary_content
        }
        
        # Save to vault
        vault_dir = os.path.join(ROOT_DIR, "vault", "scouts")
        os.makedirs(vault_dir, exist_ok=True)
        
        filename = f"SCOUT_{datetime.now().strftime('%H%M%S')}.json"
        save_path = os.path.join(vault_dir, filename)
        
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        logging.info(f"💾 Scout report saved to {save_path}")
        return f"Mission successful. Scraped '{title}'. Report archived in vault."
    except Exception as e:
        logging.error(f"Scout error: {e}")
        return f"Error scouting URL: {str(e)}"
    finally:
        await engine.close()

if __name__ == "__main__":
    import json # Import here to be safe
    parser = argparse.ArgumentParser(description="X-LINK Browser Scout")
    parser.add_argument("--url", required=True, help="URL to scout")
    args = parser.parse_args()
    
    asyncio.run(scout_url(args.url))
