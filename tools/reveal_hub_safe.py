import argparse
import asyncio
import os
import sys
from typing import TYPE_CHECKING

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if TYPE_CHECKING:
    from x_link_engine import XLinkEngine

DEFAULT_HUB_URL = "http://localhost:5001/hub/index.html?startup_home=1"


def is_hub_url(url: str) -> bool:
    return "localhost:5001/hub" in url or "127.0.0.1:5001/hub" in url


def is_startup_leftover_url(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    return lowered in {
        "about:blank",
        "chrome://newtab/",
        "chrome-error://chromewebdata/",
    }


async def close_startup_leftovers(engine, keep_page) -> int:
    closed = 0
    if not engine.context:
        return closed

    for page in list(engine.context.pages):
        if keep_page is not None and page == keep_page:
            continue
        try:
            if is_startup_leftover_url(page.url):
                await page.close()
                closed += 1
        except Exception:
            continue
    return closed


async def reveal(target_url: str) -> int:
    print(f"Targeted Hub: {target_url}")

    from x_link_engine import XLinkEngine

    engine = XLinkEngine()
    if not await engine.connect():
        print("Could not connect to the current Brave session. Please ensure Brave is running with --remote-debugging-port=9222.")
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
            try:
                if target_page.url != target_url:
                    await target_page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                # If a reused tab cannot be refreshed cleanly, fall back to the target URL through
                # the normal page-management path rather than preserving stale workspace state.
                target_page = await engine.ensure_page(
                    target_url,
                    wait_sec=1,
                    bring_to_front=True,
                    reuse_existing=True,
                    verify_session=False,
                )
            await target_page.bring_to_front()
            closed = await close_startup_leftovers(engine, target_page)
            if closed:
                print(f"Reused existing X-LINK Hub tab and closed {closed} startup leftover tab(s).")
            else:
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
            closed = await close_startup_leftovers(engine, page)
            if closed:
                print(f"X-LINK Hub opened and focused, and cleaned up {closed} startup leftover tab(s).")
            else:
                print("X-LINK Hub opened and focused in your current Brave session.")
        return 0
    finally:
        await engine.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Focus the X-LINK Hub tab without spawning duplicates.")
    parser.add_argument("--url", default=DEFAULT_HUB_URL, help="Hub URL to reuse or open.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(reveal(args.url)))
