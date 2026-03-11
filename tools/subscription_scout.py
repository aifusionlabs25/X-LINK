"""
SUBSCRIPTION SCOUT — Autonomous Billing Intelligence
=====================================================
Sloane visits each target's billing/settings page, scrapes:
  - Plan name & tier
  - Monthly/annual cost
  - Renewal / next invoice date
  - Payment method (if visible)

Results are saved to vault/reports/SUBSCRIPTION_REGISTRY.json
and emailed to aifusionlabs@gmail.com.
"""

import asyncio
import os
import sys
import json
import re
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# ── Per-platform billing scrapers ────────────────────────────────────

async def scout_tavus(engine, page):
    """Scout Tavus billing page for plan, cost, renewal."""
    info = {"platform": "Tavus", "url": "https://platform.tavus.io/dev/billing"}
    try:
        page = await engine.ensure_page(info["url"], wait_sec=5)
        text = await page.locator('body').inner_text()

        # Plan name
        for plan in ['Enterprise', 'Scale', 'Growth', 'Starter', 'Free']:
            if plan.lower() in text.lower():
                info['plan'] = plan
                break

        # Cost — look for "$X.XX/mo" or "$X/month" patterns
        cost_match = re.search(r'\$[\d,.]+\s*/?\s*(?:mo(?:nth)?|yr|year|annually)?', text, re.I)
        if cost_match:
            info['cost'] = cost_match.group(0).strip()

        # Renewal / next invoice
        date_match = re.search(r'(?:next\s*(?:invoice|billing|renewal|payment)|renews?\s*(?:on)?)\s*[:\-]?\s*(\w+\s+\d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})', text, re.I)
        if date_match:
            info['renewal_date'] = date_match.group(1).strip()

        await page.close()
    except Exception as e:
        info['error'] = str(e)
    return info


async def scout_anam(engine, page):
    """Scout Anam billing/settings for plan and usage."""
    info = {"platform": "Anam AI", "url": "https://lab.anam.ai/settings"}
    try:
        page = await engine.ensure_page("https://lab.anam.ai/settings", wait_sec=5)
        text = await page.locator('body').inner_text()

        for plan in ['Pro', 'Growth', 'Explorer', 'Starter', 'Free']:
            if plan.lower() in text.lower():
                info['plan'] = plan
                break

        cost_match = re.search(r'\$[\d,.]+\s*/?\s*(?:mo(?:nth)?|yr|year)?', text, re.I)
        if cost_match:
            info['cost'] = cost_match.group(0).strip()

        date_match = re.search(r'(?:next\s*(?:invoice|billing|renewal)|renews?)\s*[:\-]?\s*(\w+\s+\d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})', text, re.I)
        if date_match:
            info['renewal_date'] = date_match.group(1).strip()

        await page.close()
    except Exception as e:
        info['error'] = str(e)
    return info


async def scout_vercel(engine, page):
    """Scout Vercel for plan and usage limits."""
    info = {"platform": "Vercel", "url": "http://vercel.com/robs-projects-e72bad73/~/usage"}
    try:
        page = await engine.ensure_page(info["url"], wait_sec=5)
        text = await page.locator('body').inner_text()

        for plan in ['Enterprise', 'Pro', 'Hobby', 'Free']:
            if plan.lower() in text.lower():
                info['plan'] = plan
                break

        cost_match = re.search(r'\$[\d,.]+\s*/?\s*(?:mo(?:nth)?|yr|year)?', text, re.I)
        if cost_match:
            info['cost'] = cost_match.group(0).strip()

        bw_match = re.search(r'([\d,.]+\s*(?:GB|TB))\s*(?:of|/)\s*([\d,.]+\s*(?:GB|TB))', text, re.I)
        if bw_match:
            info['bandwidth'] = f"{bw_match.group(1)} / {bw_match.group(2)}"

        await page.close()
    except Exception as e:
        info['error'] = str(e)
    return info


async def scout_resend(engine, page):
    """Scout Resend billing for plan, cost, and email quota."""
    info = {"platform": "Resend", "url": "https://resend.com/settings/billing"}
    try:
        page = await engine.ensure_page(info["url"], wait_sec=5)
        text = await page.locator('body').inner_text()

        for plan in ['Enterprise', 'Pro', 'Starter', 'Free']:
            if plan.lower() in text.lower():
                info['plan'] = plan
                break

        cost_match = re.search(r'\$[\d,.]+\s*/?\s*(?:mo(?:nth)?|yr|year)?', text, re.I)
        if cost_match:
            info['cost'] = cost_match.group(0).strip()

        quota_match = re.search(r'([\d,]+)\s*/?\s*([\d,]+)\s*emails?', text, re.I)
        if quota_match:
            info['email_quota'] = f"{quota_match.group(1)} / {quota_match.group(2)}"

        date_match = re.search(r'(?:next\s*(?:invoice|billing|renewal)|renews?)\s*[:\-]?\s*(\w+\s+\d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})', text, re.I)
        if date_match:
            info['renewal_date'] = date_match.group(1).strip()

        await page.close()
    except Exception as e:
        info['error'] = str(e)
    return info


async def scout_cartesia(engine, page):
    """Scout Cartesia for credits and plan."""
    info = {"platform": "Cartesia", "url": "https://play.cartesia.ai/console"}
    try:
        page = await engine.ensure_page(info["url"], wait_sec=5)
        text = await page.locator('body').inner_text()

        for plan in ['Enterprise', 'Scale', 'Growth', 'Starter', 'Free']:
            if plan.lower() in text.lower():
                info['plan'] = plan
                break

        credit_match = re.search(r'([\d,.]+)\s*(?:credits?|characters?)\s*(?:remaining|left|available)', text, re.I)
        if credit_match:
            info['credits_remaining'] = credit_match.group(1)

        cost_match = re.search(r'\$[\d,.]+\s*/?\s*(?:mo(?:nth)?|yr|year)?', text, re.I)
        if cost_match:
            info['cost'] = cost_match.group(0).strip()

        await page.close()
    except Exception as e:
        info['error'] = str(e)
    return info


async def scout_elevenlabs(engine, page):
    """Scout ElevenLabs for plan, quota, and cost."""
    info = {"platform": "ElevenLabs", "url": "https://elevenlabs.io/app/subscription"}
    try:
        page = await engine.ensure_page(info["url"], wait_sec=5)
        text = await page.locator('body').inner_text()

        for plan in ['Enterprise', 'Scale', 'Pro', 'Starter', 'Creator', 'Free']:
            if plan.lower() in text.lower():
                info['plan'] = plan
                break

        cost_match = re.search(r'\$[\d,.]+\s*/?\s*(?:mo(?:nth)?|yr|year)?', text, re.I)
        if cost_match:
            info['cost'] = cost_match.group(0).strip()

        char_match = re.search(r'([\d,]+)\s*(?:of\s*)?([\d,]+)\s*characters?', text, re.I)
        if char_match:
            info['character_quota'] = f"{char_match.group(1)} / {char_match.group(2)}"

        date_match = re.search(r'(?:next\s*(?:invoice|billing|renewal)|renews?)\s*[:\-]?\s*(\w+\s+\d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})', text, re.I)
        if date_match:
            info['renewal_date'] = date_match.group(1).strip()

        await page.close()
    except Exception as e:
        info['error'] = str(e)
    return info


# ── Main Scout Routine ───────────────────────────────────────────────

async def main():
    print(f"\n{'='*60}")
    print(f"  🔍 SUBSCRIPTION SCOUT — Billing Intelligence Sweep")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    engine = XLinkEngine()
    if not await engine.connect():
        print("❌ CDP connection failed.")
        return

    scouts = [
        scout_tavus,
        scout_anam,
        scout_vercel,
        scout_resend,
        scout_cartesia,
        scout_elevenlabs,
    ]

    registry = []

    for scout_fn in scouts:
        try:
            info = await scout_fn(engine, None)
            registry.append(info)
            status = "✅" if 'plan' in info or 'cost' in info else "⚠️"
            print(f"  {status} {info.get('platform', '?')}: plan={info.get('plan', '?')}, cost={info.get('cost', '?')}, renewal={info.get('renewal_date', '?')}")
        except Exception as e:
            print(f"  ❌ Scout failed: {e}")
            registry.append({"platform": "Unknown", "error": str(e)})

    # Save registry
    registry_path = os.path.join(ROOT_DIR, 'vault', 'reports', 'SUBSCRIPTION_REGISTRY.json')
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)

    output = {
        "generated": datetime.now().isoformat(),
        "source": "Subscription Scout v1 (autonomous)",
        "subscriptions": registry
    }

    with open(registry_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  📁 Registry saved: {registry_path}")

    # Build email body
    email_lines = [
        "Subscription Intelligence Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} MST",
        "=" * 50,
        ""
    ]
    for sub in registry:
        email_lines.append(f"📦 {sub.get('platform', '?')}")
        email_lines.append(f"   Plan: {sub.get('plan', 'Not detected')}")
        email_lines.append(f"   Cost: {sub.get('cost', 'Not detected')}")
        email_lines.append(f"   Renewal: {sub.get('renewal_date', 'Not detected')}")
        if sub.get('bandwidth'):
            email_lines.append(f"   Bandwidth: {sub['bandwidth']}")
        if sub.get('email_quota'):
            email_lines.append(f"   Email Quota: {sub['email_quota']}")
        if sub.get('character_quota'):
            email_lines.append(f"   Characters: {sub['character_quota']}")
        if sub.get('credits_remaining'):
            email_lines.append(f"   Credits Left: {sub['credits_remaining']}")
        if sub.get('error'):
            email_lines.append(f"   ⚠️ Error: {sub['error']}")
        email_lines.append("")

    email_body = "\n".join(email_lines)

    # Send email via gsuite_handler
    print("\n  📧 Dispatching report to aifusionlabs@gmail.com...")
    try:
        import subprocess
        PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
        subprocess.Popen([
            PYTHON_EXE,
            os.path.join(ROOT_DIR, "tools", "gsuite_handler.py"),
            "--action", "gmail_send",
            "--to", "aifusionlabs@gmail.com",
            "--subject", f"📦 Subscription Scout Report — {datetime.now().strftime('%Y-%m-%d')}",
            "--body", email_body
        ])
        print("  ✅ Email dispatch initiated.")
    except Exception as e:
        print(f"  ❌ Email dispatch failed: {e}")

    await engine.close()

    print(f"\n{'='*60}")
    print(f"  🔍 SUBSCRIPTION SCOUT COMPLETE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
