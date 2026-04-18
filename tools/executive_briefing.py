import os
import re
import json
import glob
import asyncio
import sys
import subprocess
import logging
import requests
from datetime import datetime

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")

def get_moneypenny_tone_dynamic(context_summary):
    """
    Calls Ollama to generate a dynamic Moneypenny briefing.
    """
    OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
    
    system_prompt = """
SYSTEM PERSONA: SLOANE (Code name Moneypenny)
VOICE: Polished British, dry wit, ultra-efficient, slightly judgmental but loyal.
CONTEXT: Chief of Staff to Rob at AI Fusion Labs.
DIRECTIVE: Synthesize the provided mission data into a concise, high-status briefing for Rob.

STRICT RULES:
1. Maximum 3 sentences.
2. Output ONLY the briefing text. No greetings like "Good day," no salutations, no letter sign-offs like "Best regards, Sloane".
3. Do NOT invent details, dates, schedules, technical experts, or "redacted" security items. 
4. If a fact is not in the MISSION DATA, do not mention it.
    """
    
    user_prompt = f"[MISSION DATA]\n{context_summary}\n\n[COMMAND]\nProvide the briefing directly. Follow all STRICT RULES."
    
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": "qwen2.5:14b-instruct-q6_K",
            "messages": [
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.4,
                "stop": ["Best regards", "Sincerely", "Sloane"]
            }
        }, timeout=30)
        
        reply = response.json().get("message", {}).get("content", "").strip()
        if not reply:
            return "System online. Data is flowing, though your attention seems... divided."
        return reply
    except Exception as e:
        logging.error(f"Ollama Briefing Error: {e}")
        return "I'm here, Founder. The brain is a bit sluggish today—perhaps it needs a refill of whatever you're drinking."

def send_sloane_email(subject, body, to="aifusionlabs@gmail.com"):
    """
    Sends an email as Sloane via Gmail UI (gsuite_handler).
    No external API key needed — uses Brave browser automation.
    """
    WHITELIST = ["aifusionlabs@gmail.com", "rvicks@gmail.com"]
    if not any(w in to.lower() for w in WHITELIST):
        print(f"🛑 Sloane Security Alert: Unauthorized recipient {to} blocked.")
        return

    try:
        subprocess.Popen([
            PYTHON_EXE,
            os.path.join(ROOT_DIR, "tools", "gsuite_handler.py"),
            "--action", "gmail_send",
            "--to", to,
            "--subject", subject,
            "--body", body
        ])
        print(f"✅ Executive Briefing dispatched via Gmail to {to}")
    except Exception as e:
        print(f"❌ Gmail dispatch failed: {e}")

def get_latest_eval_summaries(root_dir):
    """Aggregates the most recent evaluation results for each agent."""
    eval_dir = os.path.join(root_dir, 'vault', 'evals', 'batches')
    if not os.path.exists(eval_dir):
        return []
    
    agent_results = {}
    for summary_path in glob.glob(os.path.join(eval_dir, '**', 'batch_summary.json'), recursive=True):
        batch_id = os.path.basename(os.path.dirname(summary_path))
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                agent_raw = data.get("target_agent", "unknown")
                agent_key = agent_raw.lower().strip()
                mtime = os.path.getmtime(summary_path)
                
                if agent_key not in agent_results or mtime > agent_results[agent_key]['mtime']:
                    agent_results[agent_key] = {
                        "agent": agent_raw,
                        "score": data.get("average_score", 0),
                        "tests": data.get("total_runs", 0),
                        "verdict": data.get("verdict", "N/A"),
                        "batch_id": batch_id,
                        "mtime": mtime
                    }
        except: continue
            
    results = list(agent_results.values())
    results.sort(key=lambda x: x['mtime'], reverse=True)
    for r in results: r.pop('mtime', None) # Clean up
    return results

def get_latest_strategic_synthesis(root_dir):
    """Scans vault/intel for the latest Pro Research report and extracts the synthesis."""
    intel_dir = os.path.join(root_dir, 'vault', 'intel')
    reports = glob.glob(os.path.join(intel_dir, 'PRO_RESEARCH_*.md'))
    if not reports:
        return None, None
    
    latest_report = max(reports, key=os.path.getmtime)
    try:
        with open(latest_report, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract Title
        title_match = re.search(r'# 💎 Pro Research: (.*)', content)
        title = title_match.group(1).strip() if title_match else "Latest Intelligence"
        
        # Extract Synthesis (between ## Strategic Synthesis and next ## OR end of file)
        synthesis_match = re.search(r'## Strategic Synthesis(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if synthesis_match:
            raw_synthesis = synthesis_match.group(1).strip()
            
            # Clean up: Remove all markdown symbols except basic punctuation
            clean_synthesis = re.sub(r'[#*_\-`\[\]()]', '', raw_synthesis)
            
            # Split into lines and filter for content
            lines = [l.strip() for l in clean_synthesis.split('\n') if l.strip()]
            
            # Priorities: Take the first 3 meaningful lines
            priorities = []
            for line in lines:
                # Skip short labels or common dividers
                if len(line) < 10 or line.lower() in ['source url', 'synthesis']:
                    continue
                priorities.append(line)
                if len(priorities) >= 3:
                    break
            
            # If still nothing, fallback to first 3 lines regardless
            if not priorities:
                priorities = lines[:3]
                
            return title, raw_synthesis.strip(), priorities
    except Exception as e:
        print(f"Error extracting synthesis: {e}")
    
    return None, None, []

def synthesize_briefing(email_push=False):
    root_dir = ROOT_DIR
    brain_dir = r"c:\AI Fusion Labs\X AGENTS\REPOS\xagents-brain"
    
    task_path = os.path.join(root_dir, 'task.md')
    backend_path = os.path.join(brain_dir, 'state', 'BACKEND_STACK.md')
    registry_path = os.path.join(brain_dir, 'state', 'AGENT_REGISTRY.md')
    history_path = os.path.join(root_dir, 'vault', 'usage_history.csv')
    log_path = os.path.join(root_dir, 'audit_synapse.log')
    
    report_dir = os.path.join(root_dir, 'vault', 'reports')
    os.makedirs(report_dir, exist_ok=True)

    def read_file(path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    calendar_events = [] # UI Scraping Deactivated
    eval_summaries = get_latest_eval_summaries(root_dir)
    
    # 3. Dynamic Intelligence Synthesis
    registry_data = read_file(registry_path)
    task_data = read_file(task_path)
    audit_log_at = read_file(log_path)
    
    # NEW: Fetch Sloane's latest Strategic Synthesis from PRO_RESEARCH
    intel_title, intel_summary, intel_priorities = get_latest_strategic_synthesis(root_dir)
    
    # Load latest audit report for blockers
    audit_blockers = []
    latest_reports = glob.glob(os.path.join(report_dir, "USAGE_AUDIT_*.json"))
    if latest_reports:
        latest_reports.sort()
        try:
            with open(latest_reports[-1], 'r') as f:
                audit_data = json.load(f)
                for target, status in audit_data.get("results", {}).items():
                    if "Blocked" in status or "404" in status:
                        audit_blockers.append(target)
        except: pass

    stability = "stable" if "Connection Established" in audit_log_at else "degraded"
    
    # Extract identifying features for Ollama context
    active_agents = re.findall(r'## (.*?)\s+—', registry_data)
    blocks = re.findall(r'- \[ \] (.*)', task_data)
    
    context_str = f"Active Agent Fleet: {', '.join(active_agents[:5])}\n"
    if blocks:
        context_str += f"Current Open Tasks: {', '.join(blocks[:3])}\n"
    else:
        context_str += "Current Open Tasks: None. The board is clear.\n"
        
    if audit_blockers:
        context_str += f"Security/Access Alerts: {', '.join(audit_blockers)}\n"
    context_str += f"Overall System Status: {stability}\n"
    
    moneypenny_briefing = get_moneypenny_tone_dynamic(context_str)

    # If we have FRESH INTEL from research, update the summary/priorities
    rd_summary = intel_title if intel_title else "Infrastructure stable. Mission parameters nominal."
    rd_priorities = intel_priorities if intel_priorities else ["Anam SDK.", "Hetzner Scale."]
    
    # If the Ollama briefing is the fallback one, OR we have FRESH intel, prioritize the intel summary
    # Sloane should sound even smarter when she has research data!
    if intel_summary:
        # Clean up synthesis for a cleaner summary (remove line breaks / too many stars)
        clean_intel = re.sub(r'[#*_\-`\[\]()]', '', intel_summary).strip()
        clean_intel = re.sub(r'\s+', ' ', clean_intel)
        moneypenny_briefing = clean_intel[:350] + ("..." if len(clean_intel) > 350 else "")
    else:
        moneypenny_briefing = get_moneypenny_tone_dynamic(context_str)

    briefing = {
        "timestamp": datetime.now().isoformat(),
        "sloane": {
            "name": "Moneypenny",
            "summary": moneypenny_briefing,
            "agent_evals": eval_summaries,
            "calendar_events": calendar_events[:5]
        },
        "departments": {
            "rd": {"summary": rd_summary, "priorities": rd_priorities},
            "sales": {"summary": "8 agents live.", "priorities": ["Legal Pro.", "Sarah-Netic Fix."]},
            "ops": {"summary": f"System is {stability}.", "priorities": ["Heartbeat.", "Cost Audit."]}
        }
    }

    report_path = os.path.join(report_dir, 'EXECUTIVE_BRIEFING_latest.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(briefing, f, indent=2)

    if email_push:
        send_sloane_email("Your Morning Briefing | X-LINK CEO Directives", moneypenny_briefing)

    print(f"✅ Moneypenny Briefing synthesized: {report_path}")
    return briefing

if __name__ == "__main__":
    push = "--email" in sys.argv
    synthesize_briefing(email_push=push)
