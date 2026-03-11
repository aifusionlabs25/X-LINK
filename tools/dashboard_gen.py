"""
DASHBOARD GENERATOR
===================
Reads the latest USAGE_AUDIT_*.json and EXECUTIVE_BRIEFING_latest.json
and bakes them into audit_hub_template.html.
"""

import os
import json
import glob
import re

def generate_dashboard():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(root_dir, 'vault', 'reports')
    template_path = os.path.join(root_dir, 'tools', 'audit_hub_template.html')
    output_path = os.path.join(root_dir, 'audit_hub.html')

    # 1. Load Audit Data
    report_files = glob.glob(os.path.join(reports_dir, 'USAGE_AUDIT_*.json'))
    audit_data = {}
    if report_files:
        latest_report = max(report_files, key=os.path.getctime)
        with open(latest_report, 'r', encoding='utf-8') as f:
            audit_data = json.load(f)
    else:
        print("⚠️ No audit reports found.")

    # 2. Load Briefing Data
    briefing_path = os.path.join(reports_dir, 'EXECUTIVE_BRIEFING_latest.json')
    briefing_data = {}
    if os.path.exists(briefing_path):
        with open(briefing_path, 'r', encoding='utf-8') as f:
            briefing_data = json.load(f)
    else:
        print("⚠️ No briefing data found.")

    # 3. Read template
    if not os.path.exists(template_path):
        print(f"❌ Template missing: {template_path}")
        return

    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # 4. Inject data (Find the tag with optional spaces and replace)
    def inject(content, tag_name, data):
        pattern = re.compile(r'\{\{\s*' + tag_name + r'\s*\}\}')
        match = pattern.search(content)
        if match:
            return content.replace(match.group(0), json.dumps(data, indent=2))
        return content

    template = inject(template, 'AUDIT_DATA_JSON', audit_data)
    template = inject(template, 'BRIEFING_DATA_JSON', briefing_data)

    # 5. Save to root
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(template)

    print(f"✅ Dashboard generated: {output_path}")

if __name__ == "__main__":
    generate_dashboard()
