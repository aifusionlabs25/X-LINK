import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


def test_compute_marathon_progress_spreads_child_progress_across_legs():
    from tools.run_eval import _compute_marathon_progress

    assert _compute_marathon_progress(1, 5, 0) == 0
    assert _compute_marathon_progress(1, 5, 50) == 10
    assert _compute_marathon_progress(3, 5, 0) == 40
    assert _compute_marathon_progress(5, 5, 100) == 100
