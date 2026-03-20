import yaml

data = """
agents:
  - name: Morgan
    slug: morgan
"""

config = yaml.safe_load(data)
agents = config.get("agents", [])

# Filter
filtered_agents = [a for a in agents if a["name"] == "Morgan"]

# Modify
filtered_agents[0]["last_synced"] = "2026-03-18"

print(f"Original config: {config}")
