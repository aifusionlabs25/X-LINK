"""
USAGE AUDITOR v1 — Automated Cost/Usage Extraction Engine
==========================================================
Connects to Brave via CDP, visits each target in usage_targets.yaml,
extracts live usage/billing metrics using the confirmed selectors,
and outputs a structured audit report.
"""

import asyncio
import os
import sys
import yaml
import json
import re
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from x_link_engine import XLinkEngine

# ── Per-platform extraction logic ────────────────────────────────────
# Each extractor receives the Playwright page and returns a dict of metrics.

async def extract_tavus(page):
    """Extract Tavus billing cycle usage."""
    metrics = {}
    try:
        # Get all text from the usage card
        card = page.locator('div.text-card-foreground.shadow-xs').first
        text = await card.inner_text()
        
        # Parse plan name
        if 'Starter' in text: metrics['plan'] = 'Starter'
        elif 'Growth' in text: metrics['plan'] = 'Growth'
        elif 'Basic' in text: metrics['plan'] = 'Basic (Free)'
        
        # Parse minutes
        match = re.search(r'([\d.]+)\s*conversation\s*minutes?\s*used', text)
        if match: metrics['conversation_minutes_used'] = match.group(1)
        
        match = re.search(r'(\d+)\s*replicas?\s*used', text)
        if match: metrics['replicas_used'] = match.group(1)
        
        match = re.search(r'(\d+)\s*video\s*generation\s*minutes?\s*used', text)
        if match: metrics['video_gen_minutes_used'] = match.group(1)
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_anam(page):
    """Extract Anam.ai usage overview."""
    metrics = {}
    try:
        # 1. On Dashboard: Try to get 'Minutes Used' from the graph or text
        minutes_used = page.locator('div:has-text("Minutes Used") + div').first
        if await minutes_used.count() > 0:
            metrics['dashboard_minutes'] = (await minutes_used.inner_text()).strip()

        # 2. If plan info is missing, navigate to sessions page
        if "/dashboard" in page.url:
            logging.info("[ANAM-AUDIT] Navigating to sessions for usage details...")
            await page.goto("https://lab.anam.ai/sessions")
            await asyncio.sleep(5)

        # Plan name/price
        plan_el = page.locator('div:has-text("Plan"), div:has-text("Subscription")').filter(has_text=re.compile(r'Starter|Growth|Pro|Explorer')).first
        if await plan_el.count() > 0:
            metrics['plan'] = (await plan_el.inner_text()).strip()

        # Usage text using specific regex for the 50/50 format
        body_text = await page.locator('body').inner_text()
        match = re.search(r'(\d+/\d+)\s*free\s*min', body_text, re.I)
        if match:
            metrics['free_minutes_summary'] = match.group(1)
        
        match = re.search(r'(\d+)\s*extra\s*min', body_text, re.I)
        if match:
            metrics['extra_minutes'] = match.group(1)

        # Fallback to general credit/minute text if specific regex fails
        if not metrics.get('free_minutes_summary'):
            match = re.search(r'(\d+)\s*minutes?\s*used', body_text, re.I)
            if match: metrics['minutes_used_total'] = match.group(1)

    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_openai(page):
    """Extract OpenAI usage dashboard."""
    metrics = {}
    try:
        content = await page.content()
        if "Verify you are human" in content or "Cloudflare" in content:
            return {"error": "Blocked by Cloudflare/CAPTCHA. Manual intervention or session refresh required."}

        # Total spend - Broad text search for dollar sign followed by numbers
        text_content = await page.locator('body').inner_text()
        match = re.search(r'\$(\d+\.\d{2})', text_content)
        if match:
            metrics['total_spend'] = match.group(0)
        
        # Budget
        match = re.search(r'limit\s*of\s*\$(\d+)', text_content, re.I)
        if match:
            metrics['budget_limit'] = match.group(0)
        
        # Get the full sidebar text to find tokens and requests
        content = page.locator('div.cmy7W').first
        text = await content.inner_text()
        
        match = re.search(r'Total\s*tokens\s*\n?\s*([\d,.\w]+)', text)
        if match: metrics['total_tokens'] = match.group(1).strip()
        
        match = re.search(r'Total\s*requests\s*\n?\s*([\d,]+)', text)
        if match: metrics['total_requests'] = match.group(1).strip()
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_gcloud(page):
    """Extract Google Cloud billing accounts."""
    metrics = {}
    try:
        rows = await page.locator('tbody tr').all()
        accounts = []
        for row in rows:
            text = await row.inner_text()
            # Parse: AccountName \t Type \t $Amount \t ID \t Status
            parts = [p.strip() for p in text.split('\t') if p.strip()]
            if len(parts) >= 4:
                accounts.append({
                    'name': parts[0],
                    'type': parts[1] if len(parts) > 1 else '',
                    'spend': parts[2] if len(parts) > 2 else '',
                    'id': parts[3] if len(parts) > 3 else '',
                    'status': parts[4] if len(parts) > 4 else '',
                })
        metrics['accounts'] = accounts
        metrics['total_accounts'] = len(accounts)
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_vercel(page):
    """Extract Vercel usage (fallback: full page text scan)."""
    metrics = {}
    try:
        text = await page.inner_text('body')
        # Look for bandwidth, execution, etc.
        for pattern, label in [
            (r'([\d,.]+)\s*(?:GB|MB)\s*(?:of\s*)?([\d,.]+)\s*(?:GB|MB)', 'bandwidth'),
            (r'([\d,.]+)\s*(?:hours?|hrs?)\s*(?:of\s*)?([\d,.]+)', 'execution_hours'),
            (r'Bandwidth.*?([\d,.]+\s*(?:GB|MB))', 'bandwidth_used'),
            (r'Function.*?(\d[\d,.]*\s*(?:GB|MB|hrs?))', 'function_usage'),
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metrics[label] = match.group(0).strip()[:100]
        
        if not metrics:
            # Grab first 500 chars for manual review
            metrics['raw_preview'] = text[:500].strip()
            metrics['status'] = 'no_patterns_matched'
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_resend(page):
    """Extract Resend billing (fallback: full page text scan)."""
    metrics = {}
    try:
        text = await page.inner_text('body')
        for pattern, label in [
            (r'([\d,]+)\s*/\s*([\d,]+)\s*emails', 'emails_quota'),
            (r'([\d,]+)\s*emails?\s*sent', 'emails_sent'),
            (r'\$[\d,.]+', 'cost_found'),
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metrics[label] = match.group(0).strip()
        
        if not metrics:
            metrics['raw_preview'] = text[:500].strip()
            metrics['status'] = 'no_patterns_matched'
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_cartesia(page):
    """Extract Cartesia console usage."""
    metrics = {}
    try:
        # 1. Try to find credits on the main page
        content = await page.locator('body').inner_text()
        match = re.search(r'([\d,.]+)\s*Credits', content, re.I)
        if match:
            metrics['total_credits'] = match.group(1)
            return metrics

        # 2. Trigger User Menu (top right profile)
        logging.info("[CARTESIA-AUDIT] Triggering user menu for credit balance...")
        # Broad locators for the top-right profile circle/button
        profile_btn = page.locator('button[aria-haspopup="menu"], button:has-text("AI"), .rounded-full, [aria-label*="profile"]').last
        if await profile_btn.count() > 0:
            await profile_btn.click()
            await asyncio.sleep(3)
            
            # Re-scan for menu text
            content = await page.locator('body').inner_text()
            match = re.search(r'([\d,.]+)\s*credits?\s*', content, re.I)
            if match:
                metrics['credits_extracted'] = match.group(1)
                return metrics
        
        # Fallback to general scan
        if not metrics:
            label = page.locator('h4:has-text("Usage")').first
            value = page.locator('span:has-text("Credits")').first
            if await label.count() > 0:
                metrics['total_usage_label'] = (await label.inner_text()).strip()
                metrics['total_usage_value'] = (await value.inner_text()).strip()
        
        # Per-capability
        blocks = await page.locator('div.relative.rounded-md div.flex.flex-col').all()
        capabilities = []
        for block in blocks[:10]:  # Limit
            text = (await block.inner_text()).strip()
            if text and 'Credits' in text:
                lines = text.split('\n')
                if len(lines) >= 2:
                    capabilities.append({'name': lines[0], 'value': lines[1]})
        metrics['capabilities'] = capabilities
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


async def extract_elevenlabs(page):
    """Extract Elevenlabs usage/credits."""
    metrics = {}
    try:
        # 1. Try main page first
        text = await page.locator('body').inner_text()
        match = re.search(r'Remaining:\s*([\d,]+)', text, re.I)
        if match:
            metrics['credits_remaining'] = match.group(1)
            return metrics

        # 2. Trigger User Menu (top right circle)
        logging.info("[ELEVENLABS-AUDIT] Triggering user menu for credit balance...")
        # Profile icon usually has a letter or percentage
        profile_btn = page.locator('button:has-text("%"), .rounded-full, [aria-label*="Account"]').last
        if await profile_btn.count() > 0:
            await profile_btn.click()
            await asyncio.sleep(3)
            
            # Scan menu
            menu_text = await page.locator('body').inner_text()
            # "Remaining: 10,000" or similar
            match = re.search(r'(?:Remaining|Balance|Total):\s*([\d,]+)', menu_text, re.I)
            if match:
                metrics['credits_found'] = match.group(1)

    except Exception as e:
        metrics['error'] = str(e)
    return metrics


# ── Map target names to extractors ───────────────────────────────────
EXTRACTORS = {
    'Tavus Usage': extract_tavus,
    'Tavus Billing': extract_tavus,
    'Anam Lab Dashboard': extract_anam,
    'Anam Lab Sessions': extract_anam,
    # 'OpenAI Usage': extract_openai,        # WEEKLY MANUAL — MFA/Cloudflare blocks automation
    # 'Google Cloud Billing': extract_gcloud, # WEEKLY MANUAL — legacy rvicks@gmail.com account
    'Vercel Usage': extract_vercel,
    'Resend Billing': extract_resend,
    'Cartesia Console': extract_cartesia,
    'Elevenlabs Usage': extract_elevenlabs,
}


async def main():
    # ── Load targets ──────────────────────────────────────────────
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'usage_targets.yaml')
    with open(yaml_path, 'r') as f:
        config = yaml.safe_load(f)
    
    targets = config.get('targets', [])
    
    print(f"\n{'='*60}")
    print(f"  ⚡ USAGE AUDITOR v1 — Live Extraction Run")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🎯 {len(targets)} targets loaded")
    print(f"{'='*60}\n")
    
    # ── Connect ───────────────────────────────────────────────────
    engine = XLinkEngine()
    if not await engine.connect():
        print("❌ CDP connection failed.")
        return
    
    audit_results = {}
    
    for target in targets:
        name = target['name']
        url = target['url']
        
        print(f"\n{'─'*50}")
        print(f"  📊 {name}")
        print(f"  📎 {url}")
        
        try:
            # Pass account_email for Google/Gmail services
            account_email = "novaaifusionlabs@gmail.com" if ("google.com" in url or "gmail.com" in url) else None
            page = await engine.ensure_page(url, wait_sec=4, account_email=account_email)
            await page.bring_to_front()
            await asyncio.sleep(3)
            
            # ── SECURITY HANDSHAKE ──────────────────────────────────────────
            wall_issue = await engine.detect_security_wall(page)
            if wall_issue:
                print(f"  🚨 SECURITY WALL DETECTED: {wall_issue}")
                logging.warning(f"SECURITY_ALERT: Moneypenny hit a {wall_issue} wall at {name}. Founder intervention required.")
                
                # POST to Hub for Founder Intervention Alert
                try:
                    import requests as req
                    req.post("http://127.0.0.1:5001/api/intervention", json={
                        "url": url,
                        "service": name,
                        "issue": wall_issue,
                        "message": f"I'm stuck at {name}. The page shows a '{wall_issue}' barrier. I need you to manually resolve this — please navigate to the tab and handle the login/verification, then click 'Resume Mission' on the Hub."
                    }, timeout=5)
                except Exception as post_err:
                    logging.error(f"Intervention POST failed: {post_err}")
                
                audit_results[name] = {
                    'url': url,
                    'status': 'blocked',
                    'issue': wall_issue,
                    'timestamp': datetime.now().isoformat(),
                }
                continue
            
            extractor = EXTRACTORS.get(name)
            if extractor:
                metrics = await extractor(page)
            else:
                text = await page.inner_text('body')
                metrics = {'raw_preview': text[:500], 'status': 'no_extractor'}
            
            audit_results[name] = {
                'url': url,
                'metric_type': target.get('metric', 'Unknown'),
                'timestamp': datetime.now().isoformat(),
                'data': metrics,
            }
            
            # ── SLOANE JANITOR: AUTO-CLOSE ─────────────────────────────────
            # Essential tabs to keep: Hub, Gmail, Calendar.
            # dash dashboards (Tavus, Cartesia, etc.) should be closed to save resources.
            core_fragments = ["audit_hub.html", "mail.google.com", "calendar.google.com"]
            is_core = any(f in url for f in core_fragments)
            
            if not is_core:
                print(f"  🧹 Sloane Janitor: Closing {name} dashboard...")
                await page.close()
            
            # Print results
            if 'error' in metrics:
                print(f"  ❌ Error: {metrics['error']}")
            else:
                for key, val in metrics.items():
                    if key in ('raw_preview',):
                        print(f"  📝 {key}: {str(val)[:80]}...")
                    elif isinstance(val, list):
                        print(f"  📋 {key}: {len(val)} items")
                        for item in val[:5]:
                            print(f"      → {item}")
                    else:
                        print(f"  ✅ {key}: {val}")
                
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            audit_results[name] = {
                'url': url,
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            }
        
        await asyncio.sleep(1)
    
    # ── Save report ───────────────────────────────────────────────
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vault', 'reports')
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"USAGE_AUDIT_{timestamp}.json")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(audit_results, f, indent=2, ensure_ascii=False)
    
    # ── Print summary ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  📊 AUDIT COMPLETE — SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Platform':<25} {'Key Metric':>30}")
    print(f"  {'─'*25} {'─'*30}")
    
    for name, result in audit_results.items():
        data = result.get('data', {})
        if 'error' in data or 'error' in result:
            summary = f"❌ {(data.get('error') or result.get('error', ''))[:25]}"
        elif 'total_spend' in data:
            summary = f"💰 {data['total_spend']}"
        elif 'conversation_minutes_used' in data:
            summary = f"⏱️  {data['conversation_minutes_used']} min used"
        elif 'free_minutes_used' in data:
            summary = f"⏱️  {data['free_minutes_used']}/{data.get('free_minutes_total','?')} min"
        elif 'credits_remaining' in data:
            summary = f"🎫 {data['credits_remaining']} credits left"
        elif 'total_usage_value' in data:
            summary = f"📊 {data['total_usage_value']}"
        elif 'accounts' in data:
            spends = [a.get('spend','$?') for a in data['accounts']]
            summary = f"☁️  {', '.join(spends)}"
        elif 'status' in data and data['status'] == 'no_patterns_matched':
            summary = "⚠️  No patterns matched"
        else:
            summary = "✅ Data captured"
        
        print(f"  {name:<25} {summary:>30}")
    
    print(f"\n  📁 Full report: {report_path}")
    print(f"{'='*60}\n")
    
    await engine.close()

    # ── Auto-generate Dashboard ───────────────────────────────────
    try:
        from tools.dashboard_gen import generate_dashboard
        generate_dashboard()
    except Exception as e:
        print(f"⚠️  Dashboard generation skipped: {e}")



if __name__ == "__main__":
    asyncio.run(main())
