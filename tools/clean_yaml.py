import yaml
import os

path = os.path.join(os.getcwd(), 'config', 'agents.yaml')

# We load the raw file and fix common smart quotes and utf8 misinterpretations
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace typical smart quotes and character weirdness
content = content.replace('â€"', "—")
content = content.replace('â€™', "'")
content = content.replace('â€œ', '"')
content = content.replace('â€\x9d', '"')
content = content.replace('â€˜', "'")
content = content.replace('’', "'")
content = content.replace('‘', "'")
content = content.replace('“', '"')
content = content.replace('”', '"')
content = content.replace('—', "-") # Just make it a standard dash for safety

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Now check if yaml parses it safely
try:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    print("✅ YAML parses standard UTF-8 successfully.")
except Exception as e:
    print(f"❌ Error parsing YAML: {e}")
