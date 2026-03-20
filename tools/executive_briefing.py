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
            "model": "qwen3-coder-next",
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
    for batch_id in os.listdir(eval_dir):
        batch_path = os.path.join(eval_dir, batch_id)
        if not os.path.isdir(batch_path): continue
            
        summary_path = os.path.join(batch_path, 'batch_summary.json')
        if not os.path.exists(summary_path): continue
            
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
    for r in results: r.pop('mtime', None) # Clean up
    results.sort(key=lambda x: x['score'], reverse=True)
    return results

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
    audit_log = read_file(log_path)
    
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

    stability = "stable" if "Connection Established" in audit_log else "degraded"
    
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

    rd_summary = "Infrastructure stable. Mission parameters nominal."
    
    briefing = {
        "timestamp": datetime.now().isoformat(),
        "sloane": {
            "name": "Moneypenny",
            "summary": moneypenny_briefing,
            "agent_evals": eval_summaries,
            "calendar_events": calendar_events[:5]
        },
        "departments": {
            "rd": {"summary": rd_summary, "priorities": ["Anam SDK.", "Hetzner Scale."]},
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
