import os
import glob
import re

ROOT_DIR = os.getcwd()
HISTORY_DIR = os.path.join(ROOT_DIR, 'vault', 'mel', 'history')
AGENTS_PATH = os.path.join(ROOT_DIR, 'config', 'agents.yaml')

def extract_persona(log_file):
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
    # Personas in MEL logs start at line 1 and end before evaluation results
    # We'll take everything until the first '---' or 'Evaluation Results' or similar.
    # Looking at the Amy log, it appears to be the full persona.
    lines = content.splitlines()
    persona_lines = []
    for line in lines:
        if 'MEL EVALUATION RESULTS' in line or '---' in line:
            break
        persona_lines.append(line)
    return "\n".join(persona_lines).strip()

def rebuild():
    print("🚀 Starting reconstruction of agents.yaml...")
    
    # 1. Map slugs to latest history files
    logs = glob.glob(os.path.join(HISTORY_DIR, '*.txt'))
    latest_logs = {}
    for log in logs:
        basename = os.path.basename(log)
        slug = basename.split('_')[0]
        if slug not in latest_logs or os.path.getctime(log) > os.path.getctime(latest_logs[slug]):
            latest_logs[slug] = log

    # 2. Hardcoded order from agents.yaml
    slug_order = ['morgan', 'sarah-netic', 'dani', 'amy', 'james', 'luke', 'claire', 'taylor', 'michael']
    
    # 3. Load other metadata from current (corrupted) file if possible
    # Actually, we'll just reconstruct the basic structure for now.
    
    new_content = "agents:\n"
    
    for slug in slug_order:
        print(f"  Analysing {slug}...")
        log_path = latest_logs.get(slug)
        if not log_path:
            print(f"  ⚠️ No log found for {slug}. Using simple placeholder.")
            persona = "You are a helpful assistant."
        else:
            persona = extract_persona(log_path)
            print(f"  ✅ Extracted {len(persona.splitlines())} lines from {os.path.basename(log_path)}")

        # Indent the persona for YAML multiline
        indented_persona = "\n    ".join(persona.splitlines())
        
        # Simple template (SDR-style)
        new_content += f"- slug: {slug}\n"
        new_content += f"  name: {slug.capitalize()}\n"
        new_content += f"  persona: |\n    {indented_persona}\n"
        new_content += "  eval:\n    must_collect: []\n" # Placeholders for now

    with open(AGENTS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✨ Reconstructed agents.yaml written to {AGENTS_PATH}")

if __name__ == "__main__":
    rebuild()
