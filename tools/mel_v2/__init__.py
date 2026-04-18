"""
MEL v2 package.

Provides cleaner contract parsing, simulation, and evaluation orchestration
without disturbing the legacy MEL path.
"""

from .engine import evaluate_prompt_v2, run_evolution_v2

__all__ = ["evaluate_prompt_v2", "run_evolution_v2"]
