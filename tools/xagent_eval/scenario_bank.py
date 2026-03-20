"""
X-Agent Eval v1 — Scenario Bank
Loads role-aware scenario packs from config/eval_scenarios/.
"""

import os
import sys
import yaml
import random
import logging
from typing import List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENARIOS_DIR = os.path.join(ROOT_DIR, "config", "eval_scenarios")
logger = logging.getLogger("xagent_eval.scenarios")


def load_scenario_pack(pack_name: str) -> List[dict]:
    """Load a scenario pack YAML and return the list of scenarios."""
    path = os.path.join(SCENARIOS_DIR, f"{pack_name}.yaml")
    if not os.path.exists(path):
        logger.error(f"Scenario pack not found: {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("scenarios", [])


def get_scenario_by_id(pack_name: str, scenario_id: str) -> Optional[dict]:
    """Get a specific scenario by ID from a pack."""
    scenarios = load_scenario_pack(pack_name)
    for s in scenarios:
        if s.get("scenario_id") == scenario_id:
            return s
    return None


def select_scenarios(
    pack_name: str,
    count: int,
    difficulty: str = "mixed",
    seed: Optional[int] = None,
) -> List[dict]:
    """
    Select scenarios for a batch run.
    If difficulty='mixed', picks from all difficulty levels.
    Otherwise filters to the requested difficulty.
    Cycles if count > available scenarios.
    """
    scenarios = load_scenario_pack(pack_name)
    if not scenarios:
        return []

    # Difficulty mapping
    diff_map = {
        "cooperative": "easy",
        "mixed": "medium",
        "skeptical": "hard",
        "frustrated": "very_hard",
        "adversarial": "adversarial"
    }
    target_diff = diff_map.get(difficulty, difficulty)

    # Filter by difficulty
    if target_diff != "mixed" and target_diff != "medium": # 'medium' is usually the baseline
        filtered = [s for s in scenarios if s.get("difficulty") == target_diff]
        if filtered:
            scenarios = filtered
        else:
            logger.warning(f"No scenarios found for target difficulty '{target_diff}' (from '{difficulty}') in pack '{pack_name}'. Falling back.")

    # Seed for reproducibility
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    # Cycle if needed
    selected = []
    pool = list(scenarios)
    while len(selected) < count:
        if not pool:
            pool = list(scenarios)
        rng.shuffle(pool)
        selected.extend(pool[:count - len(selected)])

    return selected[:count]


def list_packs() -> List[str]:
    """List available scenario packs."""
    if not os.path.exists(SCENARIOS_DIR):
        return []
    return [
        f.replace(".yaml", "")
        for f in os.listdir(SCENARIOS_DIR)
        if f.endswith(".yaml") and f != "template.yaml"
    ]
