"""
DISCOVERY SCOUT v2 — Usage Auditor Selector Finder
===================================================
Systematically visits each URL in usage_targets.yaml,
sniffs the DOM for elements containing currency ($) or
usage-unit keywords, and prints candidate selectors.
"""

import asyncio
import os
import sys
import yaml
import re
import json
from datetime import datetime

# Allow imports from parent dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from x_link_engine import XLinkEngine

# ── Keywords that signal a usage/billing metric ──────────────────────
USAGE_PATTERNS = [
    r'\$\d',                    # Dollar amounts like $12.50
    r'\d+\s*credits?',          # "500 credits"
    r'\d+\s*minutes?',          # "120 minutes"
    r'\d+\s*characters?',       # "10,000 characters"
    r'\d+\s*tokens?',           # "1M tokens"
    r'\d+\s*emails?',           # "300 emails"
    r'\d+\s*requests?',         # "1,000 requests"
    r'\d+\s*hours?',            # "5 hours"
    r'\d+\s*GB',                # "100 GB"
    r'\d+\s*MB',                # "500 MB"
    r'\d+[\.,]\d+\s*%',        # Percentages like "85.2%"
    r'usage',                   # Generic "usage" keyword
    r'remaining',               # "remaining"
    r'quota',                   # "quota"
    r'plan[\s:]+',              # "Plan: Pro"
    r'billing\s*period',        # "Billing Period"
    r'current\s*spend',         # "Current Spend"
    r'total\s*cost',            # "Total Cost"
]

COMBINED_PATTERN = '|'.join(USAGE_PATTERNS)


async def sniff_page(engine, target: dict) -> list:
    """
    Navigate to the target URL (auto-recovering the tab if needed),
    then scan the DOM for elements containing usage/billing signals.
    Returns a list of candidate dicts.
    """
    name = target['name']
    url  = target['url']
    
    print(f"\n{'='*60}")
    print(f"  🔍 SCANNING: {name}")
    print(f"  📎 URL: {url}")
    print(f"{'='*60}")
    
    try:
        page = await engine.ensure_page(url, wait_sec=4)
    except Exception as e:
        print(f"  ❌ FAILED to load tab: {e}")
        return []
    
    # Bring to front and give the page time to fully render
    await page.bring_to_front()
    await asyncio.sleep(3)
    
    # ── JavaScript DOM sniffer ─────────────────────────────────────
    # Walks the visible DOM, finds leaf/near-leaf text nodes whose
    # content matches our usage patterns, and returns metadata.
    candidates = await page.evaluate("""(pattern) => {
        const regex = new RegExp(pattern, 'i');
        const results = [];
        const seen = new Set();
        
        // Walk all elements
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_ELEMENT,
            null
        );
        
        let node;
        while (node = walker.nextNode()) {
            // Skip hidden elements
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
            
            // Get the direct text content (not deeply nested children)
            const directText = Array.from(node.childNodes)
                .filter(c => c.nodeType === Node.TEXT_NODE)
                .map(c => c.textContent.trim())
                .join(' ')
                .trim();
            
            // Also check the full innerText for short elements
            const fullText = node.innerText ? node.innerText.trim() : '';
            const textToCheck = fullText.length < 500 ? fullText : directText;
            
            if (!textToCheck || textToCheck.length < 2) continue;
            if (seen.has(textToCheck)) continue;
            
            if (regex.test(textToCheck)) {
                seen.add(textToCheck);
                
                // Build a class path
                const buildPath = (el) => {
                    const parts = [];
                    let cur = el;
                    for (let i = 0; i < 3 && cur && cur !== document.body; i++) {
                        let seg = cur.tagName.toLowerCase();
                        if (cur.id) seg += '#' + cur.id;
                        if (cur.className && typeof cur.className === 'string') {
                            seg += '.' + cur.className.split(/\\s+/).filter(c => c).slice(0, 2).join('.');
                        }
                        parts.unshift(seg);
                        cur = cur.parentElement;
                    }
                    return parts.join(' > ');
                };
                
                results.push({
                    text: textToCheck.substring(0, 200),
                    id: node.id || null,
                    tag: node.tagName.toLowerCase(),
                    classPath: buildPath(node),
                    selector: node.id 
                        ? '#' + node.id 
                        : (node.className && typeof node.className === 'string' && node.className.trim()
                            ? node.tagName.toLowerCase() + '.' + node.className.trim().split(/\\s+/)[0]
                            : node.tagName.toLowerCase()),
                    rect: (() => {
                        const r = node.getBoundingClientRect();
                        return { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) };
                    })()
                });
            }
        }
        
        // Deduplicate and limit
        return results.slice(0, 25);
    }""", COMBINED_PATTERN)
    
    if not candidates:
        print(f"  ⚠️  No usage/billing candidates found on this page.")
        print(f"      (Page may require login or uses dynamic rendering)")
    else:
        print(f"  ✅ Found {len(candidates)} candidate(s):\n")
        for i, c in enumerate(candidates):
            print(f"  [{i+1}] ─────────────────────────────────────────")
            print(f"      Text:      {c['text'][:120]}")
            print(f"      Tag:       <{c['tag']}>")
            print(f"      ID:        {c['id'] or '(none)'}")
            print(f"      ClassPath: {c['classPath']}")
            print(f"      Selector:  {c['selector']}")
            print(f"      Position:  top={c['rect']['top']}px, left={c['rect']['left']}px, {c['rect']['w']}x{c['rect']['h']}")
    
    return candidates


async def main():
    # ── Load targets ───────────────────────────────────────────────
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'usage_targets.yaml')
    with open(yaml_path, 'r') as f:
        config = yaml.safe_load(f)
    
    targets = config.get('targets', [])
    print(f"\n🚀 DISCOVERY SCOUT v2 — Usage Auditor Selector Finder")
    print(f"   Loaded {len(targets)} targets from usage_targets.yaml\n")
    
    # ── Connect engine ─────────────────────────────────────────────
    engine = XLinkEngine()
    if not await engine.connect():
        print("❌ Could not connect to CDP. Is Brave running with --remote-debugging-port=9222?")
        return
    
    all_results = {}
    
    for target in targets:
        results = await sniff_page(engine, target)
        all_results[target['name']] = {
            'url': target['url'],
            'metric': target['metric'],
            'candidates': results
        }
        # Small delay between tabs to avoid overwhelming the browser
        await asyncio.sleep(1)
    
    # ── Save discovery report ──────────────────────────────────────
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vault', 'reports')
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"DISCOVERY_SCOUT_{timestamp}.json")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"  📊 DISCOVERY COMPLETE")
    print(f"  📁 Full report saved to: {report_path}")
    print(f"{'='*60}")
    
    # ── Summary table ──────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  {'Target':<30} {'Candidates Found':>15}")
    print(f"{'─'*60}")
    for name, data in all_results.items():
        count = len(data['candidates'])
        status = f"✅ {count}" if count > 0 else "⚠️  0"
        print(f"  {name:<30} {status:>15}")
    print(f"{'─'*60}\n")
    
    await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
