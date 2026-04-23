import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


def test_resolve_agent_default_pack_prefers_eval_block():
    from tools.marathon_runner import resolve_agent_default_pack

    agent = {
        "slug": "evan",
        "default_pack": "legacy_pack",
        "eval": {"default_pack": "evan_moving"},
    }

    assert resolve_agent_default_pack(agent, "evan") == "evan_moving"


def test_resolve_agent_default_pack_falls_back_to_slug_pack():
    from tools.marathon_runner import resolve_agent_default_pack

    agent = {"slug": "evan", "eval": {}}

    assert resolve_agent_default_pack(agent, "evan") == "evan_pack"


def test_init_marathon_session_tracks_selected_difficulties():
    from tools.marathon_runner import _init_marathon_session

    session = _init_marathon_session(
        {
            "agents": ["evan"],
            "difficulty": ["easy", "medium", "adversarial"],
            "runs": 5,
            "review_mode": "compact",
            "environment": "local",
        },
        "marathon/test",
        3,
    )

    assert session["type"] == "marathon"
    assert session["selected_difficulties"] == ["easy", "medium", "adversarial"]
    assert session["total_legs"] == 3
