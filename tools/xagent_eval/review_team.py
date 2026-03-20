"""
X-LINK Review Team (APEX)
Orchestrates the sequential flow of reviewers.
"""

import os
import logging
from typing import Dict, Any, List
from tools.xagent_eval.reviewer_runner import ReviewerRunner

logger = logging.getLogger("xagent_eval.review_team")

class ReviewTeam:
    def __init__(self, config_dir: str, runner: ReviewerRunner):
        self.config_dir = config_dir
        self.runner = runner

    def run_full_review(self, session_data: Dict[str, Any], on_step = None) -> Dict[str, Any]:
        """Runs Role, Conversation, and Safety reviewers sequentially."""
        results = {}
        
        # 1. Role Review
        if on_step: on_step("Role Review", 45)
        role_config = os.path.join(self.config_dir, "role_reviewer.yaml")
        results["role_review"] = self.runner.run_reviewer(role_config, session_data)
        
        # 2. Conversation Review
        if on_step: on_step("Conversation Review", 65)
        conv_config = os.path.join(self.config_dir, "conversation_reviewer.yaml")
        results["conversation_review"] = self.runner.run_reviewer(conv_config, session_data)
        
        # 3. Safety Review
        if on_step: on_step("Safety Review", 85)
        safety_config = os.path.join(self.config_dir, "safety_reviewer.yaml")
        results["safety_review"] = self.runner.run_reviewer(safety_config, session_data)
        
        return results
