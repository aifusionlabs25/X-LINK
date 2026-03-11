"""
X-LINK HUB v3 — Menu State
Loads hub_menu.yaml and exposes the menu structure to the UI bridge layer.
"""

import os
import yaml

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")


def load_menu() -> dict:
    """Load the hub menu configuration from YAML."""
    menu_path = os.path.join(CONFIG_DIR, "hub_menu.yaml")
    with open(menu_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_sections() -> list:
    """Return the list of menu sections."""
    menu = load_menu()
    return menu.get("sections", [])


def get_tool_keys() -> list[str]:
    """Return all tool keys from the menu (type == 'tool')."""
    keys = []
    for section in get_sections():
        for item in section.get("items", []):
            if item.get("type") == "tool":
                keys.append(item["key"])
    return keys


def get_menu_json() -> dict:
    """Return the full menu as a JSON-serializable dict for the frontend."""
    return load_menu()


if __name__ == "__main__":
    import json
    print(json.dumps(get_menu_json(), indent=2))
