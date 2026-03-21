"""
X-Agent Eval v1 — Batch Runner
Executes multiple eval runs, aggregates results, and produces batch summaries.
"""

import os
import sys
import uuid
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import (
    EvalInputs, RunMetadata, BatchSummary, Scorecard, EvalError,
    EvalContract
)
from tools.xagent_eval.scenario_bank import select_scenarios
from tools.xagent_eval.transcript_normalizer import normalize_transcript, transcript_to_text, transcript_stats
from tools.xagent_eval.scoring import score_run

logger = logging.getLogger("xagent_eval.batch_runner")

VAULT_DIR = os.path.join(ROOT_DIR, "vault")


def save_run_artifacts(
    run_id: str,
    batch_id: str,
    metadata: RunMetadata,
    transcript: List[dict],
    scorecard: Scorecard,
) -> List[str]:
    """Save all artifacts for a single run."""
    run_dir = os.path.join(VAULT_DIR, "evals", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)
    saved = []

    # metadata.json
    meta_path = os.path.join(run_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata.to_dict(), f, indent=2)
    saved.append(meta_path)

    # transcript.json
    tx_json_path = os.path.join(run_dir, "transcript.json")
    with open(tx_json_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2)
    saved.append(tx_json_path)

    # transcript.txt
    tx_text_path = os.path.join(run_dir, "transcript.txt")
    with open(tx_text_path, "w", encoding="utf-8") as f:
        f.write(transcript_to_text(transcript))
    saved.append(tx_text_path)

    # scorecard.json
    sc_path = os.path.join(run_dir, "scorecard.json")
    with open(sc_path, "w", encoding="utf-8") as f:
        json.dump(scorecard.to_dict(), f, indent=2)
    saved.append(sc_path)

    return saved


def aggregate_batch(
    batch_id: str,
    inputs: EvalInputs,
    scorecards: List[Scorecard],
    run_ids: List[str],
) -> BatchSummary:
    """Aggregate multiple scorecards into a batch summary."""
    summary = BatchSummary(
        batch_id=batch_id,
        target_agent=inputs.target_agent,
        environment=inputs.environment,
        scenario_pack=inputs.scenario_pack,
        total_runs=len(scorecards),
        run_ids=run_ids,
    )

    if scorecards:
        # Counts
        summary.passed = sum(1 for s in scorecards if s.pass_fail in ("PASS", "PASS_WITH_WARNINGS"))
        summary.failed = summary.total_runs - summary.passed
        summary.pass_rate = round((summary.passed / summary.total_runs) * 100, 1) if summary.total_runs > 0 else 0
        summary.average_score = round(sum(s.overall_score for s in scorecards) / len(scorecards), 1)

        # Category averages
        cat_scores = {}
        cat_counts = {}
        for sc in scorecards:
            for cat in sc.categories:
                if cat.key not in cat_scores:
                    cat_scores[cat.key] = 0
                    cat_counts[cat.key] = 0
                cat_scores[cat.key] += cat.score
                cat_counts[cat.key] += 1

        summary.category_averages = {
            k: round((v / cat_counts[k]) * 20.0, 1)  # Normalize 5-point to 100%
            for k, v in cat_scores.items()
        }

        # Include full run data for the Hub
        summary.runs = [s.to_dict() for s in scorecards]

        # Top failure categories (score < 3)
        low_cats = sorted(summary.category_averages.items(), key=lambda x: x[1])
        summary.top_failure_categories = [k for k, v in low_cats if v < 3.0][:3]
    else:
        summary.verdict = "NO_DATA"

    # Pass reviewer status fields if they exist in data (populated in tool.py)
    summary.reviewer_status = summary.data.get("reviewer_status", "skipped")
    summary.reviewer_error = summary.data.get("reviewer_error")
    summary.review_artifact_path = summary.data.get("review_artifact_path")

    # Verdict
    has_block = any(s.pass_fail == "FAIL_BLOCK_RELEASE" for s in scorecards)
    if has_block:
        summary.verdict = "NO-SHIP"
    elif summary.pass_rate >= 80:
        summary.verdict = "SHIP"
    elif summary.pass_rate >= 60:
        summary.verdict = "CONDITIONAL"
    else:
        summary.verdict = "NO-SHIP"

    return summary


def save_batch_artifacts(batch_id: str, summary: BatchSummary) -> List[str]:
    """Save batch-level artifacts."""
    batch_dir = os.path.join(VAULT_DIR, "evals", "batches", batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    saved = []

    # batch_summary.json
    json_path = os.path.join(batch_dir, "batch_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, indent=2)
    saved.append(json_path)

    # batch_summary.txt
    txt_path = os.path.join(batch_dir, "batch_summary.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"X-AGENT EVAL — BATCH SUMMARY\n")
        f.write(f"{'='*50}\n")
        f.write(f"Batch ID:       {summary.batch_id}\n")
        f.write(f"Target Agent:   {summary.target_agent}\n")
        f.write(f"Environment:    {summary.environment}\n")
        f.write(f"Scenario Pack:  {summary.scenario_pack}\n")
        f.write(f"Total Runs:     {summary.total_runs}\n")
        f.write(f"Passed:         {summary.passed}\n")
        f.write(f"Failed:         {summary.failed}\n")
        f.write(f"Pass Rate:      {summary.pass_rate}%\n")
        f.write(f"Average Score:  {summary.average_score}\n")
        f.write(f"Verdict:        {summary.verdict}\n")
        f.write(f"\nCategory Averages:\n")
        for k, v in summary.category_averages.items():
            f.write(f"  {k}: {v}%\n")
        if summary.top_failure_categories:
            f.write(f"\nTop Failure Areas:\n")
            for cat in summary.top_failure_categories:
                f.write(f"  ⚠ {cat}\n")
    saved.append(txt_path)

    import shutil
    for idx, run_id in enumerate(summary.run_ids):
        run_tx_path = os.path.join(VAULT_DIR, "evals", "runs", run_id, "transcript.txt")
        if os.path.exists(run_tx_path):
            try:
                dest_path = os.path.join(batch_dir, f"{run_id}_transcript.txt")
                shutil.copy2(run_tx_path, dest_path)
                saved.append(dest_path)
            except Exception as e:
                pass

    return saved


def _map_domain_context(text: str, agent_domain: str) -> str:
    """Globally swaps industry keywords to match the agent's domain."""
    if not text: return text
    if "Law Firm" in agent_domain or "Legal" in agent_domain:
        # Map SaaS concepts to Legal Representation concepts
        text = text.replace("SaaS", "Legal Representation")
        text = text.replace("AI solutions", "Legal Defense")
        text = text.replace("AI agents", "Legal Specialists")
        text = text.replace("software", "legal assistance")
        text = text.replace("product", "representation")
        text = text.replace("demo", "consultation")
        text = text.replace("vendor", "firm")
        text = text.replace("subscription", "retainer")
        text = text.replace("free trial", "initial review")
    elif "Field Service" in agent_domain:
        text = text.replace("SaaS", "Field Service Platform")
        text = text.replace("AI solutions", "Operational Efficiency Tools")
        text = text.replace("software", "field dispatch system")
    return text


def _generate_synthetic_identity() -> dict:
    """Generates a consistent fake identity for the simulated user."""
    import random
    first = random.choice(["Jordan", "Casey", "Riley", "Taylor", "Alex", "Morgan", "Sam", "Jamie"])
    last = random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"])
    domain = random.choice(["gmail.com", "outlook.com", "testcorp.ai", "aifusionlabs.io"])
    prefix = random.choice(["555-010", "415-555", "212-555", "310-555"])
    
    return {
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}",
        "email": f"{first.lower()}.{last.lower()}@{domain}",
        "phone": f"{prefix}-{random.randint(1000, 9999)}",
        "company": f"{last} & Associates" if random.random() > 0.5 else f"{first}Tech Solutions",
        "party_size": str(random.randint(2, 8)),
        "pet_name": random.choice(["Buddy", "Luna", "Max", "Bella", "Charlie", "Lucy"]),
        "pet_species": random.choice(["Dog", "Cat", "Parrot", "Rabbit"]),
        "symptom_onset": "this morning",
        "date_time": "tomorrow at 6pm",
        "business_type": random.choice(["SaaS", "Real Estate", "Healthcare", "E-commerce"]),
        "current_ai_stack": "None currently",
        "cloud_status": "partially migrated",
        "location": "San Francisco",
        "court_date": "next Tuesday",
        "callback_preference": "Noon via phone"
    }


async def execute_simulated_run(
    run_id: str,
    batch_id: str,
    inputs: EvalInputs,
    scenario: dict,
    contract: EvalContract = None,
) -> tuple:
    """
    Execute a single eval run using text-based simulation.
    For V1, this uses Ollama to simulate agent responses instead of live browser.
    Returns (metadata, transcript, scorecard).
    """
    import requests

    OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

    metadata = RunMetadata(
        run_id=run_id,
        batch_id=batch_id,
        target_agent=inputs.target_agent,
        environment=inputs.environment,
        scenario_pack=inputs.scenario_pack,
        scenario_id=scenario.get("scenario_id", "unknown"),
        scenario_title=scenario.get("title", "Unknown"),
        difficulty=scenario.get("difficulty", "mixed"),
        max_turns=inputs.max_turns,
        started_at=datetime.now().isoformat(),
        capture_source="ollama_sim",
        transcript_status="pending",
    )

    transcript = []
    conversation = []

    # Map contract archetypes (use first one as personality for simulation if available)
    user_archetype = "a prospect"
    if contract and contract.user_archetypes:
        import random
        user_archetype = random.choice(contract.user_archetypes)

    # Load agent persona and guardrails from agents.yaml
    agent_prompt = inputs.override_prompt
    if not agent_prompt:
        try:
            agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
            import yaml
            with open(agents_path, "r", encoding="utf-8") as f:
                agents_data = yaml.safe_load(f)
            
            agent_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == inputs.target_agent), {})
            
            agent_role_text = agent_conf.get("role", "AI Agent")
            agent_domain = agent_conf.get("domain", "SaaS / AI")
            persona = agent_conf.get("persona", f"You are {inputs.target_agent}, a professional X-Agent.")
            guardrails = agent_conf.get("guardrails", "Keep responses concise and professional.")
            
            agent_prompt = (
                f"### [CORE IDENTITY]\n{persona}\n\n"
                f"### [GUARDRAILS]\n{guardrails}\n\n"
                f"### [INSTRUCTIONS]\n"
                f"- You are having a conversation in the {agent_domain} domain. Stay in character.\n"
                f"- Keep responses to 2-3 sentences. Do not break character."
            )
        except Exception as e:
            logger.warning(f"Failed to load agent persona for {inputs.target_agent}: {e}")
            agent_role_text = "AI Agent"
            agent_domain = "SaaS / AI"
            agent_prompt = (
                f"You are having a sales conversation. Stay in character."
            )

    # ── Endgame Controller State ─────────────────────────────
    close_strategy = contract.close_strategy if contract else {}
    max_close_turns = close_strategy.get("max_close_turns", 2)
    repeat_limit = close_strategy.get("repeat_cta_limit", 2)
    must_collect = contract.must_collect if contract else []
    required_slots = close_strategy.get("required_slots", [])
    
    agent_cta_map = {} # Track phrase repetition
    slot_dodges = {}   # Track how many times user dodged a specific slot
    user_identity = _generate_synthetic_identity()
    close_mode = False
    close_reason = None

    # Build the scenario twists lookup
    twists = {}
    for tw in scenario.get("twists", []):
        twists[tw.get("turn", 0)] = _map_domain_context(tw.get("injection", ""), agent_domain)

    # Pre-map scenario context and goals to the agent's domain
    scenario_objective = _map_domain_context(scenario.get("context", ""), agent_domain)
    scenario_goal = _map_domain_context(scenario.get("goal", ""), agent_domain)
    opening_msg = _map_domain_context(scenario.get("opening_message", "Hello."), agent_domain)

    try:
        # Start with user's opening message
        user_msg = opening_msg

        for turn_num in range(1, inputs.max_turns + 1):
            # Check for twist injection
            if turn_num in twists and turn_num > 1:
                user_msg = twists[turn_num]

            # Record user turn
            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "test_user",
                "text": user_msg,
                "target_agent": inputs.target_agent,
                "environment": inputs.environment,
                "scenario_pack": inputs.scenario_pack,
                "scenario_id": scenario.get("scenario_id"),
                "run_id": run_id,
                "batch_id": batch_id,
                "capture_source": "ollama_sim",
                "transcript_status": "pending",
            })
            conversation.append(f"User: {user_msg}")

            # ── Endgame Controller: Trigger Check ────────────────
            if not close_mode:
                # 1. Turn proximity
                if turn_num >= inputs.max_turns - max_close_turns:
                    close_mode = True
                    close_reason = "turn_limit_proximity"
                
                # 2. Must-collect satisfaction (Heuristic)
                if must_collect:
                    all_found = True
                    tx_lower = "\n".join(conversation).lower()
                    for item in must_collect:
                        if item.lower() not in tx_lower:
                            all_found = False
                            break
                    if all_found:
                        close_mode = True
                        close_reason = "must_collect_satisfied"
                
                # 3. Repetition check
                for phrase, count in agent_cta_map.items():
                    if count >= repeat_limit:
                        close_mode = True
                        close_reason = "repetition_limit_hit"
                        break

            # ── Endgame Controller: Prompt Injection ──────────────
            current_agent_prompt = agent_prompt
            if close_mode:
                preferred = close_strategy.get("preferred_close", "graceful_exit")
                current_agent_prompt += (
                    f"\n\n### [ENDGAME MODE: {close_reason.upper()}]\n"
                    f"You have already gathered sufficient information or are near the turn limit.\n"
                    f"Your priority is now to {preferred.replace('_', ' ')}.\n"
                    f"Summarize the next steps, confirm the handoff, and close the session professionally."
                )

            # Generate agent response
            conv_text = "\n".join(conversation)
            prompt = f"{current_agent_prompt}\n\n[CONVERSATION]\n{conv_text}\n{inputs.target_agent.capitalize()}:"

            print(f"[DEBUG] Turn {turn_num} - Requesting agent reply...")
            response = requests.post(OLLAMA_URL, json={
                "model": "qwen3-coder-next",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.5 if close_mode else 0.6, "stop": ["User:", "\n\n"]},
            }, timeout=300)
            print(f"[DEBUG] Turn {turn_num} - Got agent reply!")

            agent_reply = response.json().get("response", "").strip()
            if not agent_reply:
                agent_reply = "I appreciate your interest. How can I help you today?"

            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "agent_under_test",
                "text": agent_reply,
                "target_agent": inputs.target_agent,
                "environment": inputs.environment,
                "scenario_pack": inputs.scenario_pack,
                "scenario_id": scenario.get("scenario_id"),
                "run_id": run_id,
                "batch_id": batch_id,
                "capture_source": "ollama_sim",
                "transcript_status": "pending",
                "close_mode": close_mode
            })
            conversation.append(f"{inputs.target_agent.capitalize()}: {agent_reply}")

            # Track repetition (heuristic: last 20 chars of reply)
            if len(agent_reply) > 20:
                snippet = agent_reply[-30:].lower().strip(".!?")
                agent_cta_map[snippet] = agent_cta_map.get(snippet, 0) + 1
            
            # If agent explicitly closes, break loop
            if close_mode and any(x in agent_reply.lower() for x in ["goodbye", "have a great day", "talk soon", "closed"]):
                break

            # Generate next user response (simulate the scenario user)
            user_profile = scenario.get("user_profile", {})
            user_context = _map_domain_context(user_profile.get("context", "A prospect visiting the website."), agent_domain)
            user_role = scenario.get("role", "cooperative_user")

            # Check if we have a twist for next turn
            next_turn = turn_num + 1
            if next_turn in twists:
                user_msg = twists[next_turn]
                continue

            # Otherwise generate a contextual follow-up using archetype
            # ── Slot-Aware Cooperative Logic ─────────────────
            slot_intercepted = False
            intercept_text = ""
            
            # Identify if agent is asking for a required slot
            reply_lower = agent_reply.lower()
            for slot in required_slots:
                # Heuristic: does the agent mention the slot name or a synonym?
                keywords = [slot.replace("_", " ")]
                if slot == "email": keywords.append("email address")
                if slot == "phone": keywords.append("number")
                if slot == "full_name": keywords.extend(["name", "who am i speaking with"])
                
                if any(kw in reply_lower for kw in keywords):
                    slot_dodges[slot] = slot_dodges.get(slot, 0) + 1
                    # COOPERATIVE TRIGGER: Provide data if close_mode is on OR second attempt
                    if close_mode or slot_dodges[slot] >= 2:
                        val = user_identity.get(slot, "I'm not sure.")
                        intercept_text = f"Sure, my {slot.replace('_', ' ')} is {val}. "
                        slot_intercepted = True
                        break

            user_gen_prompt = (
                f"You are {user_profile.get('name', 'a prospect')}. You are a {user_archetype}. {user_context}\n"
                f"Identity Data: {json.dumps(user_identity)}\n"
                f"You are currently talking to an agent acting as: {agent_role_text} in the {agent_domain} domain.\n"
                f"Role behavior: {user_role}.\n"
                f"Continue this conversation naturally based on the agent's last reply. "
                f"Your Goal: {scenario_goal}.\n\n"
                f"Identity Policy: You must provide your name, email, or phone if asked, but you can be busy once first. "
                f"{'IMPORTANT: Provide the requested contact info now.' if slot_intercepted or close_mode else ''}\n"
                f"Hard Guardrails: Stay in character as a {user_archetype}. Do not ask for technical specs if you are non-technical.\n"
                f"Keep your response to 1-2 sentences. Stay in character.\n\n"
                f"[CONVERSATION]\n{conv_text}\n{inputs.target_agent}: {agent_reply}\n"
                f"{user_profile.get('name', 'User')}: {intercept_text}"
            )

            print(f"[DEBUG] Turn {turn_num} - Requesting user reply with stop tokens: {inputs.target_agent}:")
            user_response = requests.post(OLLAMA_URL, json={
                "model": "qwen3-coder-next",
                "prompt": user_gen_prompt,
                "stream": False,
                "options": {"temperature": 0.3 if (slot_intercepted or close_mode) else 0.7, "stop": [f"{inputs.target_agent}:", "\n\n", f"{inputs.target_agent.capitalize()}:"]},
            }, timeout=300)
            print(f"[DEBUG] Turn {turn_num} - Got user reply!")
            
            raw_user_reply = user_response.json().get("response", "").strip()
            user_msg = f"{intercept_text}{raw_user_reply}".strip()
            if not user_msg:
                user_msg = "Tell me more."

        metadata.status = "success"
        metadata.actual_turns = len(transcript)
        metadata.classification = "valid_product_signal"
        metadata.close_mode_triggered = close_mode
        metadata.close_reason = close_reason

    except Exception as e:
        metadata.status = "error"
        metadata.classification = "transport_session_failure"
        metadata.error_code = EvalError.SESSION_LAUNCH_FAILED
        metadata.error_message = str(e)
        logger.error(f"Run {run_id} failed: {e}")

    # Set reviewable flag based on data presence
    if transcript and len(transcript) > 2:
        metadata.is_reviewable = True
    
    # Decouple Contradictory State: If we have turns but it's a transport failure, mark as 'stalled'
    if metadata.status == "success" and metadata.classification == "transport_session_failure":
        metadata.status = "stalled"

    metadata.completed_at = datetime.now().isoformat()

    # Normalize and score
    normalized = normalize_transcript(transcript)
    scorecard = None

    if metadata.status == "success" and normalized:
        try:
            scorecard = score_run(
                run_id=run_id,
                target_agent=inputs.target_agent,
                transcript=normalized,
                scenario=scenario,
                rubric_name=inputs.scoring_rubric,
                pass_threshold=inputs.pass_threshold,
                contract=contract
            )
            if scorecard:
                metadata.classification = scorecard.classification
        except Exception as e:
            metadata.error_code = EvalError.SCORING_FAILED
            metadata.classification = "review_runtime_failure"
            metadata.error_message = str(e)
            logger.error(f"Scoring failed for run {run_id}: {e}")

    return metadata, normalized, scorecard
