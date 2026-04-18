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
