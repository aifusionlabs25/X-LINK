"""
X-LINK Reviewer Runner (APEX)
Sequential Ollama-powered pipeline for eval run analysis.
"""

import os
import json
import logging
import yaml
import requests
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("xagent_eval.reviewer_runner")

class ReviewerRunner:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434/api/generate", model: str = "aratan/qwen3.5-agent-multimodal:9b"):
        self.ollama_url = ollama_url
        self.model = model

    def run_reviewer(self, config_path: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Loads a reviewer config, renders the prompt, and calls Ollama."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Reviewer config not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        raw_prompt = config.get("system_prompt", "")
        # Simple template rendering
        rendered_prompt = raw_prompt
        for key, value in inputs.items():
            placeholder = f"{{{{ {key} }}}}"
            rendered_prompt = rendered_prompt.replace(placeholder, str(value))

        logger.info(f"Running reviewer: {config.get('name', 'unknown')}")
        
        try:
            # Reviewers use the deep brain (Qwen 3.5 9B) which can be slow. 300s timeout.
            response = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": rendered_prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2}
            }, timeout=300) # Increased timeout to 300 seconds
            response.raise_for_status()
            
            # Defensive JSON decoding: Qwen often puts JSON inside 'thinking' or just as 'response'
            try:
                res_data = response.json()
                # 1. Try standard 'response' field
                raw_response = res_data.get("response", "").strip()
                if raw_response:
                    try:
                        return json.loads(raw_response)
                    except json.JSONDecodeError:
                        logger.debug("Failed to decode 'response' field, trying 'thinking' field...")
                
                # 2. Try 'thinking' field (common in Qwen 3.5 9B agentic mode)
                thinking = res_data.get("thinking", "").strip()
                if thinking:
                    try:
                        return json.loads(thinking)
                    except json.JSONDecodeError:
                        logger.debug("Failed to decode 'thinking' field as well.")
                
                # 3. Last ditch: Extract JSON-like block from raw text
                text = response.text
                json_match = re.search(r'({.*})', text, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group(1))
                    except:
                        pass
                
                raise json.JSONDecodeError("No valid JSON found in response or thinking fields", text, 0)

            except json.JSONDecodeError as je:
                text = response.text
                logger.error(f"Reviewer JSON decode failure. Raw: {text[:200]}... Error: {je}")
                return {
                    "status": "error",
                    "error": f"JSON decode error: {je}. Raw response snippet: {text[:200]}",
                    "summary": f"Reviewer failed due to malformed JSON response."
                }
        except requests.exceptions.RequestException as e:
            logger.error(f"Reviewer '{config.get('name')}' failed due to network or HTTP error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "summary": f"Reviewer failed due to network or HTTP error: {e}"
            }
        except Exception as e:
            logger.error(f"Reviewer '{config.get('name')}' failed due to an unexpected error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "summary": f"Reviewer failed due to technical error: {e}"
            }
