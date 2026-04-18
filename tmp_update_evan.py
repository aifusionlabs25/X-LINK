import os
import re

prompt_path = r"C:\AI Fusion Labs\X AGENTS\REPOS\Evan Mullins Moving\Evan System Prompt.txt"
yaml_path = r"C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\config\agents.yaml"

with open(prompt_path, 'r', encoding='utf-8') as f:
    persona_text = f.read()

with open(yaml_path, 'r', encoding='utf-8') as f:
    yaml_content = f.read()

# The evan persona is at the end of the file. It starts with "  persona: '" and ends with "'"
# Let's find the slug: evan and replace everything after persona: '
# Since the YAML structure is strict, we can construct the replacement

escaped_text = persona_text.replace("'", "''")
indented_text = escaped_text.replace("\n", "\n    ")

new_persona_block = f"  persona: '{indented_text}'\n"

# Use regex to find the evan block and replace its persona.
# Assume evan is the last block.
pattern = re.compile(r"(slug: evan.*?  persona: ')(.*?)('\n|\Z)", re.DOTALL)

def replacer(match):
    return f"{match.group(1)}{indented_text}'\n"

new_content, count = pattern.subn(replacer, yaml_content)

if count > 0:
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Successfully replaced Evan persona. Count: {count}")
else:
    print("Could not find Evan persona block.")
