import argparse
import asyncio
import os
import sys

# Add root to path for x_link_engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from x_link_engine import XLinkEngine

DEFAULT_HUB_URL = "http://localhost:5001/hub/index.html"


def is_hub_url(url: str) -> bool:
    return "localhost:5001/hub" in url or "127.0.0.1:5001/hub" in url


async def reveal(target_url: str):
    print(f"Targeted Hub: {target_url}")

    engine = XLinkEngine()
    if not await engine.connect():
        print("❌ Could not connect to the current Brave session. Please ensure Brave is running with --remote-debugging-port=9222.")
        return 1

    try:
        hub_pages = []
        if engine.context:
            for page in engine.context.pages:
                try:
                    if is_hub_url(page.url):
                        hub_pages.append(page)
                except Exception:
                    continue

        target_page = hub_pages[-1] if hub_pages else None

        if target_page:
            for extra_page in hub_pages[:-1]:
                try:
                    await extra_page.close()
                except Exception:
                    pass
            await target_page.bring_to_front()
            print("Reused existing X-LINK Hub tab and closed older duplicates.")
        else:
            page = await engine.ensure_page(
                target_url,
                wait_sec=1,
                bring_to_front=True,
                reuse_existing=True,
                verify_session=False,
            )
            await page.bring_to_front()
            print("X-LINK Hub opened and focused in your current Brave session.")
        return 0
    finally:
        await engine.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Focus the X-LINK Hub tab without spawning duplicates.")
    parser.add_argument("--url", default=DEFAULT_HUB_URL, help="Hub URL to reuse or open.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(reveal(args.url)))
