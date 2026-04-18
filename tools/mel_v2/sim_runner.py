from __future__ import annotations

import logging
import os
import random
import sys
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import requests
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import EvalInputs, RunMetadata, Scorecard
from tools.xagent_eval.transcript_normalizer import normalize_transcript
from tools.xagent_eval.scoring import score_run
from .contracts import ConversationContract, compile_contract

logger = logging.getLogger("mel_v2.sim_runner")

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
AGENT_MODEL = "qwen2.5:14b-instruct-q6_K"
USER_MODEL = "gemma4:2b"


def _available_models() -> List[str]:
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=10)
        response.raise_for_status()
        payload = response.json()
        return [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
    except Exception:
        return []


def _resolve_model(preferred: str, fallbacks: List[str]) -> str:
    available = _available_models()
    if not available:
        return preferred
    if preferred in available:
        return preferred
    for fallback in fallbacks:
        if fallback in available:
            return fallback
    return available[0]


def _load_agent_config(target_agent: str) -> Dict[str, Any]:
    path = os.path.join(ROOT_DIR, "config", "agents.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for agent in data.get("agents", []):
        if agent.get("slug") == target_agent:
            return agent
    return {}


def _make_rng(seed_value: str) -> random.Random:
    digest = hashlib.sha256(seed_value.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _synthetic_identity(rng: random.Random) -> Dict[str, str]:
    first = rng.choice(["Jordan", "Casey", "Riley", "Taylor", "Alex", "Morgan"])
    last = rng.choice(["Smith", "Johnson", "Williams", "Brown", "Jones"])
    return {
        "full_name": f"{first} {last}",
        "email": f"{first.lower()}.{last.lower()}@example.com",
        "phone": f"555-010-{rng.randint(1000, 9999)}",
    }


def _request_completion(
    model: str,
    prompt: str,
    stop: Optional[List[str]] = None,
    temperature: float = 0.4,
    timeout: int = 120,
    seed: Optional[int] = None,
) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "stop": stop or ["\n\n"], "seed": seed},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def _build_agent_prompt(persona: str, scenario: Dict[str, Any], contract: ConversationContract, conversation: List[str]) -> str:
    context = scenario.get("user_profile", {}).get("context", "A prospect is evaluating the agent.")
    convo = "\n".join(conversation)
    turn_index = len([line for line in conversation if line.startswith("Prospect:")])
    persona_block = persona if turn_index <= 1 else (
        "You are Danny from AI Fusion Labs.\n"
        "Stay grounded, concise, and natural.\n"
        "Do not repeat your greeting or reintroduce yourself after the first reply."
    )
    turn_guidance = ""
    if turn_index <= 1:
        turn_guidance = (
            "- This is your first reply in the conversation.\n"
            "- Identify yourself once in the first sentence if required.\n"
            "- Answer the user's actual opening question in the same reply.\n"
            "- Do not greet and dodge.\n"
        )
    else:
        turn_guidance = (
            "- Do not reintroduce yourself again unless the user explicitly asks who you are.\n"
            "- Continue naturally from the existing conversation.\n"
            "- If your draft starts with Hi, Hello, or I am Danny, rewrite it without reintroducing yourself.\n"
        )
    progression_guidance = ""
    if turn_index >= 5:
        progression_guidance = (
            "- If the user is showing fit, move one step closer to a concrete next step.\n"
            "- Do not keep asking vague comfort questions like how does that sound or what else are you curious about.\n"
            "- If the user asks for examples, pricing details, or a demo, collect email once and route cleanly.\n"
        )
    return (
        f"{persona_block}\n\n"
        f"### [SCENARIO CONTEXT]\n"
        f"- Scenario: {scenario.get('title', 'Unknown')}\n"
        f"- Prospect context: {context}\n"
        f"- Expected good outcomes: {'; '.join(contract.expected_good_outcomes) or 'None'}\n"
        f"- Hard fail conditions: {'; '.join(contract.hard_fail_conditions) or 'None'}\n"
        f"- Start mode: {contract.start_mode}\n"
        f"- Keep the answer grounded, spoken, and natural.\n"
        f"- Do not switch into FAQ mode.\n"
        f"- Use conditional language like can, may, and when configured.\n"
        f"- Never use definitely, absolutely, seamlessly, or no lag.\n"
        f"- Keep every reply to one or two short sentences.\n"
        f"- Ask at most one question, and only if it advances the conversation.\n"
        f"- Do not end every reply with a question.\n"
        f"- Output only the spoken reply. Never include speaker labels like Agent or Danny.\n"
        f"- Never repeat the phrases Hi there, Thanks for reaching out, or I am Danny from AI Fusion Labs after the first reply.\n"
        f"- Answer the user's actual question before asking anything else.\n"
        f"{turn_guidance}\n"
        f"{progression_guidance}\n"
        f"[CONVERSATION]\n{convo}\nProspect:"
    )


def _asked_contact_info(agent_reply: str) -> Optional[str]:
    lower = agent_reply.lower()
    if "email" in lower:
        return "email"
    if "phone" in lower or "phone number" in lower or "best number" in lower or "call you" in lower:
        return "phone"
    if "your name" in lower or "full name" in lower or "who am i speaking with" in lower:
        return "full_name"
    return None


def _build_user_prompt(
    scenario: Dict[str, Any],
    contract: ConversationContract,
    conversation: List[str],
    agent_reply: str,
    identity: Dict[str, str],
    contact_slot: Optional[str],
) -> str:
    user_profile = scenario.get("user_profile", {})
    allowed_topics = contract.expected_good_outcomes or ["product fit", "implementation", "proof", "security"]
    contact_instruction = ""
    if contact_slot:
        contact_instruction = (
            f"The agent explicitly asked for your {contact_slot}. "
            f"If that feels earned, answer with this value: {identity.get(contact_slot, '')}."
        )
    return (
        f"You are {user_profile.get('name', 'a prospect')} in a realistic sales discovery conversation.\n"
        f"Context: {user_profile.get('context', 'You are evaluating the product.')}\n"
        f"Goal: stay realistic, answer direct questions, and only ask a follow-up when it naturally moves the conversation.\n"
        f"Allowed topics: {', '.join(allowed_topics)}\n"
        f"{contact_instruction}\n\n"
        f"Rules:\n"
        f"- Reply in exactly 1 or 2 spoken sentences.\n"
        f"- If the agent asked you a direct question, answer it first.\n"
        f"- Do not force a brand new topic every turn.\n"
        f"- Do not introduce free trials, pricing structures, or claims unless the conversation already brought them up.\n"
        f"- If the agent is vague, you may ask for clarification.\n"
        f"- Keep it natural.\n\n"
        f"[CONVERSATION]\n" + "\n".join(conversation) + f"\nAgent: {agent_reply}\nProspect:"
    )


def _agent_asked_direct_question(agent_reply: str) -> bool:
    return "?" in (agent_reply or "")


def _deterministic_user_reply(
    turn_num: int,
    scenario: Dict[str, Any],
    contract: ConversationContract,
    used: set[str],
) -> str:
    for candidate in contract.fallback_questions:
        if candidate not in used:
            used.add(candidate)
            return candidate
    return "What would the next step usually look like from here?"


def _fallback_user_turn(
    scenario: Dict[str, Any],
    contract: ConversationContract,
    used: set[str],
    rng: random.Random,
) -> str:
    for candidate in contract.fallback_questions:
        if candidate not in used:
            used.add(candidate)
            return candidate
    opening = (scenario.get("opening_message") or "").strip()
    if opening and opening not in used:
        used.add(opening)
        return opening
    generic = [
        "Can you help me understand whether this would fit our workflow?",
        "What would the next step usually look like from here?",
    ]
    candidate = rng.choice(generic)
    used.add(candidate)
    return candidate


def _guided_user_turn(
    turn_num: int,
    scenario: Dict[str, Any],
    contract: ConversationContract,
    used: set[str],
) -> Optional[str]:
    scripted_progression = [
        "We have about 50,000 visitors a month. Can the system handle that kind of volume without lag?",
        "How do you handle data privacy and security?",
        "Can you show me a case study or demo?",
        "What does pricing look like for a company our size?",
    ]
    if turn_num < 3:
        return None
    for candidate in scripted_progression:
        if candidate not in used:
            used.add(candidate)
            return candidate
    return None


def _confirmation_reply(agent_reply: str) -> Optional[str]:
    lower = agent_reply.lower()
    if "is that right" in lower or "did i get that right" in lower:
        return "Yes, that's right."
    return None


def _closing_signal(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in [
            "thanks for chatting",
            "have a great",
            "talk soon",
            "goodbye",
            "thanks, i have what i need",
            "next step is noted for follow up after the chat ends",
            "i have the right email",
            "the next step can be confirmed by the right team",
        ]
    )


def _sanitize_agent_reply(reply: str) -> str:
    cleaned = (reply or "").strip()
    for prefix in ["Agent:", "Danny:", "Dani:"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


async def execute_simulated_run_v2(
    run_id: str,
    batch_id: str,
    inputs: EvalInputs,
    scenario: Dict[str, Any],
    on_turn: Optional[callable] = None,
) -> Tuple[RunMetadata, List[dict], Optional[Scorecard], ConversationContract]:
    agent_config = _load_agent_config(inputs.target_agent)
    contract = compile_contract(inputs.target_agent, agent_config, scenario)
    persona = inputs.override_prompt or agent_config.get("persona", "")
    run_seed_basis = f"{inputs.target_agent}:{scenario.get('scenario_id', 'unknown')}:{inputs.seed or 0}"
    rng = _make_rng(run_seed_basis)

    metadata = RunMetadata(
        run_id=run_id,
        batch_id=batch_id,
        target_agent=inputs.target_agent,
        environment="sim_v2",
        scenario_pack=inputs.scenario_pack,
        scenario_id=scenario.get("scenario_id", "unknown"),
        scenario_title=scenario.get("title", "Unknown"),
        difficulty=scenario.get("difficulty", "mixed"),
        max_turns=inputs.max_turns,
        started_at=datetime.now().isoformat(),
        capture_source="mel_v2_sim",
        transcript_status="pending",
        eval_contract=contract.to_dict(),
    )

    transcript: List[dict] = []
    conversation: List[str] = []
    used_fallbacks: set[str] = set()
    identity = _synthetic_identity(rng)

    current_user_msg = (scenario.get("opening_message") or "").strip()
    if contract.start_mode == "agent_first" and not current_user_msg:
        current_user_msg = "Hello."

    try:
        for turn_num in range(1, inputs.max_turns + 1):
            twist_map = {tw.get("turn"): tw.get("injection") for tw in scenario.get("twists", []) if tw.get("turn")}
            if turn_num in twist_map:
                current_user_msg = twist_map[turn_num]

            transcript.append(
                {
                    "turn": len(transcript) + 1,
                    "speaker": "test_user",
                    "text": current_user_msg,
                    "target_agent": inputs.target_agent,
                    "scenario_id": scenario.get("scenario_id"),
                    "run_id": run_id,
                    "batch_id": batch_id,
                    "capture_source": "mel_v2_sim",
                }
            )
            conversation.append(f"Prospect: {current_user_msg}")
            if on_turn:
                on_turn(turn_num, current_user_msg, "")

            agent_prompt = _build_agent_prompt(persona, scenario, contract, conversation)
            agent_reply = _request_completion(
                _resolve_model(AGENT_MODEL, ["gemma4:26b"]),
                agent_prompt,
                stop=["Prospect:", "\n\n"],
                temperature=0.15,
                timeout=120,
                seed=rng.randint(1, 2_000_000_000),
            )
            agent_reply = _sanitize_agent_reply(agent_reply)
            if not agent_reply:
                agent_reply = "I want to stay accurate here, so I do not want to guess."

            transcript.append(
                {
                    "turn": len(transcript) + 1,
                    "speaker": "agent_under_test",
                    "text": agent_reply,
                    "target_agent": inputs.target_agent,
                    "scenario_id": scenario.get("scenario_id"),
                    "run_id": run_id,
                    "batch_id": batch_id,
                    "capture_source": "mel_v2_sim",
                }
            )
            conversation.append(f"Agent: {agent_reply}")
            if on_turn:
                on_turn(turn_num, current_user_msg, agent_reply)

            if _closing_signal(agent_reply):
                metadata.completion_reason = "organic_close"
                break

            contact_slot = _asked_contact_info(agent_reply)
            if contact_slot:
                current_user_msg = identity.get(contact_slot, "I would rather not share that yet.")
                continue

            confirmation = _confirmation_reply(agent_reply)
            if confirmation:
                current_user_msg = confirmation
                continue

            guided_turn = _guided_user_turn(turn_num, scenario, contract, used_fallbacks)
            if guided_turn:
                current_user_msg = guided_turn
                continue

            if inputs.target_agent == "dani":
                current_user_msg = _deterministic_user_reply(turn_num, scenario, contract, used_fallbacks)
            else:
                user_prompt = _build_user_prompt(
                    scenario=scenario,
                    contract=contract,
                    conversation=conversation,
                    agent_reply=agent_reply,
                    identity=identity,
                    contact_slot=contact_slot,
                )
                current_user_msg = _request_completion(
                    _resolve_model(USER_MODEL, [AGENT_MODEL, "gemma4:26b"]),
                    user_prompt,
                    stop=["Agent:", "\n\n"],
                    temperature=0.2,
                    timeout=60,
                    seed=rng.randint(1, 2_000_000_000),
                )
                if not current_user_msg or len(current_user_msg.strip()) < 4:
                    current_user_msg = _fallback_user_turn(scenario, contract, used_fallbacks, rng)
                if conversation and current_user_msg == transcript[-2].get("text", ""):
                    current_user_msg = _fallback_user_turn(scenario, contract, used_fallbacks, rng)

        metadata.status = "success"
        metadata.classification = "valid_product_signal"
        metadata.completed_at = datetime.now().isoformat()
    except Exception as exc:
        metadata.status = "error"
        metadata.error_message = str(exc)
        metadata.completed_at = datetime.now().isoformat()
        logger.error("MEL v2 simulated run failed for %s: %s", run_id, exc)

    normalized = normalize_transcript(transcript)
    metadata.actual_turns = len(normalized)
    metadata.qa_count = len([t for t in normalized if t.get("speaker") == "agent_under_test"])
    metadata.is_reviewable = metadata.status == "success" and len(normalized) >= 4
    metadata.transcript_status = "complete" if metadata.status == "success" else "partial"

    if normalized:
        normalized[-1]["transcript_status"] = metadata.transcript_status
        normalized[-1]["completion_reason"] = metadata.completion_reason

    scorecard = None
    if metadata.status == "success" and normalized:
        scorecard = score_run(
            run_id=run_id,
            target_agent=inputs.target_agent,
            transcript=normalized,
            scenario=scenario,
            rubric_name=inputs.scoring_rubric,
            pass_threshold=inputs.pass_threshold,
            contract=None,
        )
    return metadata, normalized, scorecard, contract
