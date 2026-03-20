import yaml
import os

path = "config/agents.yaml"
with open(path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Find Morgan
morgan = next((a for a in config["agents"] if a["slug"] == "morgan"), None)
if morgan:
    morgan["test_ping"] = "pong"
    print("Added test_ping to Morgan")

with open(path, "w", encoding="utf-8") as f:
    yaml.dump(config, f, sort_keys=False, indent=2, allow_unicode=True)
print("Saved agents.yaml")
