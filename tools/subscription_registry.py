import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(ROOT_DIR, "vault", "reports", "SUBSCRIPTION_REGISTRY.json")


def normalize_platform_name(platform: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(platform or "").lower()).strip()
    aliases = {
        "google": "Google",
        "google play": "Google",
        "google cloud": "Google Cloud",
        "anam": "Anam AI",
        "anam ai": "Anam AI",
        "eleven labs": "ElevenLabs",
    }
    return aliases.get(cleaned, str(platform or "").strip())


def load_subscription_registry(path: str = REGISTRY_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {
            "generated": datetime.now().isoformat(),
            "source": "Hermes subscription registry",
            "subscriptions": [],
        }
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("subscriptions", [])
    return data


def save_subscription_registry(data: Dict[str, Any], path: str = REGISTRY_PATH) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["generated"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return data


def find_subscription_card(platform: str, registry: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    registry = registry or load_subscription_registry()
    target = normalize_platform_name(platform)
    target_key = re.sub(r"[^a-z0-9]+", "", target.lower())
    for sub in registry.get("subscriptions", []):
        platform_name = str(sub.get("platform") or "").strip()
        platform_key = re.sub(r"[^a-z0-9]+", "", platform_name.lower())
        if platform_key == target_key or target_key in platform_key or platform_key in target_key:
            return sub
    return None


def upsert_subscription_card(
    platform: str,
    fields: Dict[str, Any],
    *,
    path: str = REGISTRY_PATH,
    source: str = "Hermes manual update",
) -> Dict[str, Any]:
    registry = load_subscription_registry(path)
    target = normalize_platform_name(platform)
    existing = find_subscription_card(target, registry)

    clean_fields = {key: value for key, value in (fields or {}).items() if value not in (None, "", [])}
    clean_fields["platform"] = target
    clean_fields["updated_at"] = datetime.now().isoformat()
    clean_fields.setdefault("source", source)

    if existing:
        existing.update(clean_fields)
        card = existing
    else:
        card = clean_fields
        registry.setdefault("subscriptions", []).append(card)

    save_subscription_registry(registry, path)
    return card
