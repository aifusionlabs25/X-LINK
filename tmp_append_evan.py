import os

prompt_path = r"C:\AI Fusion Labs\X AGENTS\REPOS\Evan Mullins Moving\Evan System Prompt.txt"
yaml_path = r"C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\config\agents.yaml"

with open(prompt_path, 'r', encoding='utf-8') as f:
    persona_text = f.read()

# Create the YAML block matching existing structure
yaml_block = f"""- slug: evan
  name: Evan Mullins Moving
  eval:
    default_pack: evan_moving
    scoring_rubric: consultative_sales_v1
    allowed_packs:
    - evan_moving
    - evan_objections
    user_archetypes:
    - prospect
    - moving_customer
    success_event: qualified_moving_interest
  persona: '"""

# Escape single quotes in persona
persona_text = persona_text.replace("'", "''")

yaml_block += persona_text.replace("\n", "\n    ") + "'\n"

with open(yaml_path, 'a', encoding='utf-8') as f:
    f.write(yaml_block)

print(f"Appended Evan successfully, added {len(yaml_block)} bytes.")
