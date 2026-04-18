import yaml
import os

ROOT_DIR = os.getcwd()
AGENTS_PATH = os.path.join(ROOT_DIR, 'config', 'agents.yaml')
BACKUP_PATH = os.path.join(ROOT_DIR, 'back up system prompts', 'Dani X Agent Director.txt')

def inject_persona():
    # 1. Load the new persona text
    if not os.path.exists(BACKUP_PATH):
        print(f"❌ Error: Could not find backup file at {BACKUP_PATH}")
        return False
        
    with open(BACKUP_PATH, 'r', encoding='utf-8') as f:
        new_persona_text = f.read().strip()
        
    if not new_persona_text:
        print("❌ Error: New persona file is empty.")
        return False
        
    print(f"✅ Loaded {len(new_persona_text.splitlines())} lines from 'Dani X Agent Director.txt'")

    # 2. Load the current YAML securely
    try:
        with open(AGENTS_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Error parsing agents.yaml: {e}")
        return False
        
    # 3. Find and replace Dani's persona
    found = False
    for agent in data.get('agents', []):
        if agent.get('slug') == 'dani':
            agent['persona'] = new_persona_text
            found = True
            break
            
    if not found:
        print("❌ Error: 'dani' slug not found in agents.yaml")
        return False
        
    # 4. Save the YAML safely without smart quotes breaking things
    # Let yaml module handle the formatting and block strings correctly.
    try:
        with open(AGENTS_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True, explicit_start=False)
        print("✅ Successfully injected Dani's new persona and saved agents.yaml!")
        return True
    except Exception as e:
        print(f"❌ Error saving agents.yaml: {e}")
        return False

if __name__ == "__main__":
    inject_persona()
