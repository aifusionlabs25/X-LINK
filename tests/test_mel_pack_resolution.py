from tools.mel_pilot import load_agent_config, resolve_mel_scenario_pack


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
