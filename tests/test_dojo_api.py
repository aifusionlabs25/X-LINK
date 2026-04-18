import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


def test_normalize_eval_launch_params_keeps_valid_agent_pack_pair():
    from tools.dojo_api import _normalize_eval_launch_params

    params = {"agent": "amy", "pack": "amy_it_discovery"}
    normalized = _normalize_eval_launch_params(params)

    assert normalized["agent"] == "amy"
    assert normalized["pack"] == "amy_it_discovery"


def test_normalize_eval_launch_params_repairs_cross_agent_pack_mismatch():
    from tools.dojo_api import _normalize_eval_launch_params

    params = {"agent": "morgan", "pack": "amy_it_discovery"}
    normalized = _normalize_eval_launch_params(params)

    assert normalized["agent"] == "amy"
    assert normalized["pack"] == "amy_it_discovery"


def test_normalize_eval_launch_params_falls_back_to_default_pack_for_agent():
    from tools.dojo_api import _normalize_eval_launch_params

    params = {"agent": "amy", "pack": "definitely_not_a_real_pack"}
    normalized = _normalize_eval_launch_params(params)

    assert normalized["agent"] == "amy"
    assert normalized["pack"] == "amy_frontdoor_discovery"
