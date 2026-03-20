"""
X-LINK Prompt Patch Generator (Troy — APEX)
Synthesizes reviewer findings into prompt patch candidates.
"""

import os
import logging
from typing import Dict, Any
from tools.xagent_eval.reviewer_runner import ReviewerRunner

logger = logging.getLogger("xagent_eval.prompt_patch_generator")

class PromptPatchGenerator:
    def __init__(self, config_dir: str, runner: ReviewerRunner):
        self.config_dir = config_dir
        self.runner = runner

    def generate_patch(self, session_data: Dict[str, Any], review_results: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the Troy reviewer with synthesized findings."""
        troy_config = os.path.join(self.config_dir, "troy.yaml")
        
        # Merge session data with review results for Troy
        troy_inputs = session_data.copy()
        troy_inputs.update(review_results)
        
        return self.runner.run_reviewer(troy_config, troy_inputs)
