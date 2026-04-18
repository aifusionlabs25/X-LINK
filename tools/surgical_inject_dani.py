import os
import re

ROOT_DIR = os.getcwd()
AGENTS_PATH = os.path.join(ROOT_DIR, 'config', 'agents.yaml')
BACKUP_PATH = os.path.join(ROOT_DIR, 'back up system prompts', 'Dani X Agent Director.txt')

def surgical_inject():
    # 1. Load the new persona text
    if not os.path.exists(BACKUP_PATH):
        print(f"❌ Error: Could not find backup file at {BACKUP_PATH}")
        return False
        
    with open(BACKUP_PATH, 'r', encoding='utf-8') as f:
        new_persona_raw = f.read().strip()
        
    # Indent for YAML block scalar (4 spaces)
    indented_persona = new_persona_raw.replace("\n", "\n    ")
    
    # 2. Load the current YAML as raw text
    with open(AGENTS_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # 3. Regex to find the 'dani' block and replace its 'persona: |' content
    # This pattern looks for slug: dani, skip name: Dani, find persona: | and capture until the next agent (-)
    pattern = r'(- slug: dani\s+name: Dani\s+persona: \|)([\s\S]*?)(?=\n- slug:|\Z)'
    
    replacement = rf'\1\n    {indented_persona}\n'
    
    new_content, count = re.subn(pattern, replacement, content)
    
    if count == 0:
        print("❌ Error: Could not locate 'dani' block with Regex.")
        return False
        
    # 4. Save the raw text
    with open(AGENTS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print(f"✅ Successfully surgically injected {len(new_persona_raw.splitlines())} lines into Dani block.")
    return True

if __name__ == "__main__":
    surgical_inject()
