"""
X-LINK HUB v3 — Runtime: Telemetry Artifacts
Common artifact saving (screenshots, JSON, markdown) used by all tools.
"""

import os
import json
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VAULT_DIR = os.path.join(ROOT_DIR, "vault")


def save_json(category: str, filename: str, data: dict) -> str:
    """Save a JSON artifact to vault/<category>/<filename>."""
    path = os.path.join(VAULT_DIR, category, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def save_markdown(category: str, filename: str, content: str) -> str:
    """Save a markdown artifact to vault/<category>/<filename>."""
    path = os.path.join(VAULT_DIR, category, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def append_markdown(category: str, filename: str, content: str) -> str:
    """Append to a markdown artifact in vault/<category>/<filename>."""
    path = os.path.join(VAULT_DIR, category, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
    return path


async def save_screenshot(page, category: str, filename: str) -> str:
    """Save a browser screenshot to vault/<category>/<filename>."""
    path = os.path.join(VAULT_DIR, category, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    await page.screenshot(path=path)
    return path
