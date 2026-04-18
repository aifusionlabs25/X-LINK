from tools.mel_pilot import load_agent_config, resolve_mel_scenario_pack
from tools.xagent_eval.scenario_bank import load_scenario_pack


def test_amy_cooperative_default_pack_prefers_it_discovery():
    agent_config = load_agent_config("amy")

    resolved = resolve_mel_scenario_pack(
        agent_slug="amy",
        requested_pack="default_pack",
        difficulty="cooperative",
        agent_config=agent_config,
    )

    assert resolved == "amy_frontdoor_discovery"


def test_amy_mixed_default_pack_prefers_it_discovery():
    agent_config = load_agent_config("amy")

    resolved = resolve_mel_scenario_pack(
        agent_slug="amy",
        requested_pack="default_pack",
        difficulty="mixed",
        agent_config=agent_config,
    )

    assert resolved == "amy_frontdoor_discovery"


def test_amy_hard_default_pack_stays_frontdoor():
    agent_config = load_agent_config("amy")

    resolved = resolve_mel_scenario_pack(
        agent_slug="amy",
        requested_pack="default_pack",
        difficulty="hard",
        agent_config=agent_config,
    )

    assert resolved == "amy_frontdoor_discovery"


def test_amy_extreme_default_pack_stays_frontdoor():
    agent_config = load_agent_config("amy")

    resolved = resolve_mel_scenario_pack(
        agent_slug="amy",
        requested_pack="default_pack",
        difficulty="extreme",
        agent_config=agent_config,
    )

    assert resolved == "amy_frontdoor_discovery"


def test_explicit_pack_is_respected():
    agent_config = load_agent_config("amy")

    resolved = resolve_mel_scenario_pack(
        agent_slug="amy",
        requested_pack="amy_objections",
        difficulty="cooperative",
        agent_config=agent_config,
    )

    assert resolved == "amy_objections"


def test_evan_default_pack_resolves_to_real_pack():
    agent_config = load_agent_config("evan")

    resolved = resolve_mel_scenario_pack(
        agent_slug="evan",
        requested_pack="default_pack",
        difficulty="mixed",
        agent_config=agent_config,
    )

    assert resolved == "evan_moving"


def test_evan_packs_load():
    moving = load_scenario_pack("evan_moving")
    objections = load_scenario_pack("evan_objections")

    assert len(moving) >= 3
    assert len(objections) >= 2


def test_all_agent_eval_packs_exist():
    import os
    import yaml

    agents_yaml = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "agents.yaml",
    )
    scenarios_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "eval_scenarios",
    )

    with open(agents_yaml, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    missing = []
    for agent in data.get("agents", []):
        eval_block = agent.get("eval") or {}
        for pack_name in [eval_block.get("default_pack"), *(eval_block.get("allowed_packs") or [])]:
            if pack_name and not os.path.exists(os.path.join(scenarios_dir, f"{pack_name}.yaml")):
                missing.append((agent.get("slug"), pack_name))

    assert not missing, f"Missing eval scenario packs: {missing}"
