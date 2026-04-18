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
from datetime import datetime
from typing import Dict, Any, Optional
from tools.telemetry import estimate_tokens_from_text, record_llm_call

logger = logging.getLogger("xagent_eval.reviewer_runner")

class ReviewerRunner:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434/api/generate", model: str = "qwen2.5:14b-instruct-q6_K"):
        self.ollama_url = ollama_url
        self.model = model
        self.timeout = (5, 180)

    def run_reviewer(self, config_path: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Loads a reviewer config, renders the prompt, and calls Ollama."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Reviewer config not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        raw_prompt = config.get("system_prompt", "")
        model_name = config.get("model", self.model)
        strict_json = bool(config.get("strict_json", False))
        expected_keys = config.get("expected_keys", [])
        # Simple template rendering
        rendered_prompt = raw_prompt
        for key, value in inputs.items():
            placeholder = f"{{{{ {key} }}}}"
            rendered_prompt = rendered_prompt.replace(placeholder, str(value))

        logger.info(f"Running reviewer: {config.get('name', 'unknown')}")
        started_at = datetime.now()
        
        try:
            # Troy uses the deep brain (Gemma 4 26B). 120s timeout and NO 'format: json'
            # Removing 'format: json' allows Gemma 4 to use <thinking> tags without crashing.
            payload = {
                "model": model_name,
                "prompt": rendered_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 2500,  # Hard limit to kill infinite loops
                }
            }
            if strict_json:
                payload["format"] = "json"

            response = requests.post(self.ollama_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            
            res_data = response.json()
            full_text = res_data.get("response", "").strip()
            record_llm_call(
                workflow="mel_reviewer",
                provider="ollama",
                model=model_name,
                started_at=started_at,
                ended_at=datetime.now(),
                input_tokens_est=estimate_tokens_from_text(rendered_prompt),
                output_tokens_est=estimate_tokens_from_text(full_text),
                success=True,
                metadata={"reviewer": config.get("name", "unknown")},
            )

            thinking_match = re.search(r'<(?:thinking|thought)>(.*?)</(?:thinking|thought)>', full_text, re.DOTALL | re.IGNORECASE)
            thinking_process = thinking_match.group(1).strip() if thinking_match else ""

            # ── Forensic Debug Dump ───────────────────────────
            try:
                debug_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "vault", "mel", "logs")
                os.makedirs(debug_dir, exist_ok=True)
                with open(os.path.join(debug_dir, "troy_raw.txt"), "w", encoding="utf-8") as f:
                    f.write(f"MODEL: {self.model}\n")
                    f.write(f"THINKING: {thinking_process}\n")
                    f.write(f"{'='*60}\n")
                    f.write(full_text)
            except Exception as dump_err:
                logger.warning(f"Failed to dump forensic debug log: {dump_err}")

            # ── Robust JSON Extraction (Bracket-Depth Parser) ─────
            # Extract ALL top-level JSON objects using bracket counting
            # This handles nested objects that break regex-based parsers.
            json_candidates = []
            depth = 0
            start_idx = None
            for i, ch in enumerate(full_text):
                if ch == '{':
                    if depth == 0:
                        start_idx = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start_idx is not None:
                        json_candidates.append(full_text[start_idx:i+1])
                        start_idx = None

            # Try from last candidate to first (Gemma puts final answer last)
            for block in reversed(json_candidates):
                try:
                    data = json.loads(block)
                    if isinstance(data, dict) and len(data.keys()) >= 2:
                        if expected_keys and not all(key in data for key in expected_keys):
                            continue
                        if thinking_process:
                            data["thinking"] = thinking_process
                        return data
                except json.JSONDecodeError:
                    continue

            # Fallback: Try extracting between first { and last }
            first_brace = full_text.find('{')
            last_brace = full_text.rfind('}')
            if first_brace != -1 and last_brace > first_brace:
                try:
                    data = json.loads(full_text[first_brace:last_brace+1])
                    if expected_keys and not all(key in data for key in expected_keys):
                        raise json.JSONDecodeError("missing expected keys", full_text, 0)
                    if thinking_process:
                        data["thinking"] = thinking_process
                    return data
                except json.JSONDecodeError:
                    pass

            # LAST RESORT: If Troy wrote useful text but no parseable JSON,
            # wrap the raw response as a patch_candidate so MEL can still use it.
            clean_text = re.sub(r'<(?:thinking|thought)>.*?</(?:thinking|thought)>', '', full_text, flags=re.DOTALL).strip()
            if len(clean_text) > 50 and not strict_json:
                logger.warning(f"Troy returned text but no JSON. Wrapping as raw patch.")
                return {
                    "patch_candidate": clean_text,
                    "rationale": "Auto-extracted from Troy's non-JSON response.",
                    "risk_note": "This patch was not structured as JSON by Troy. Review carefully.",
                    "thinking": thinking_process,
                }

            logger.error(f"Bulletproof Parser failed. Response preview: {full_text[:500]}")
            return self._fallback_patch_response(
                thinking_process=thinking_process,
                reason="No valid JSON patch found in Troy's response.",
                raw_response=full_text[:1000],
            )

        except requests.exceptions.Timeout:
            logger.error("Troy / Scorer timed out after 120s.")
            record_llm_call(
                workflow="mel_reviewer",
                provider="ollama",
                model=model_name,
                started_at=started_at,
                ended_at=datetime.now(),
                input_tokens_est=estimate_tokens_from_text(rendered_prompt),
                output_tokens_est=0,
                success=False,
                metadata={"reviewer": config.get("name", "unknown"), "error": "timeout"},
            )
            return self._fallback_patch_response(
                reason="Inference Timeout (120s). VRAM may be locked.",
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Network/HTTP error: {e}")
            record_llm_call(
                workflow="mel_reviewer",
                provider="ollama",
                model=model_name,
                started_at=started_at,
                ended_at=datetime.now(),
                input_tokens_est=estimate_tokens_from_text(rendered_prompt),
                output_tokens_est=0,
                success=False,
                metadata={"reviewer": config.get("name", "unknown"), "error": str(e)},
            )
            return self._fallback_patch_response(reason=str(e))
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            record_llm_call(
                workflow="mel_reviewer",
                provider="ollama",
                model=model_name,
                started_at=started_at,
                ended_at=datetime.now(),
                input_tokens_est=estimate_tokens_from_text(rendered_prompt),
                output_tokens_est=0,
                success=False,
                metadata={"reviewer": config.get("name", "unknown"), "error": str(e)},
            )
            return self._fallback_patch_response(reason=str(e))

    def _fallback_patch_response(
        self,
        *,
        reason: str,
        thinking_process: str = "",
        raw_response: str = "",
    ) -> Dict[str, Any]:
        """Return a minimal heuristic patch so MEL can continue its cycle."""
        patch_candidate = (
            "- Answer the user's direct question before redirecting.\n"
            "- Keep replies to one or two short sentences.\n"
            "- Avoid repetitive email capture or handoff phrasing.\n"
            "- Stay in plain English and avoid ungrounded claims."
        )
        result = {
            "patch_candidate": patch_candidate,
            "rationale": f"Fallback heuristic patch generated because Troy did not return usable structured output. Reason: {reason}",
            "risk_note": "Heuristic fallback patch. Review carefully before promotion.",
        }
        if thinking_process:
            result["thinking"] = thinking_process
        if raw_response:
            result["raw_response"] = raw_response
        return result
