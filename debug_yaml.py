import yaml
with open("config/agents.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
    morgan = next((a for a in config["agents"] if a["slug"] == "morgan"), None)
    print(f"Morgan dict keys: {list(morgan.keys())}")
    if "last_synced" in morgan:
        print(f"last_synced: {morgan['last_synced']}")
    else:
        print("last_synced NOT FOUND")
