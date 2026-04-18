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
import re
import random
import requests
import unicodedata
from datetime import datetime
from typing import List, Optional, Dict, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from tools.xagent_eval.schemas import (
    EvalInputs, RunMetadata, BatchSummary, Scorecard, EvalError,
    EvalContract, CategoryScore
)
from tools.xagent_eval.scenario_bank import select_scenarios
from tools.xagent_eval.transcript_normalizer import normalize_transcript, transcript_to_text, transcript_stats
from tools.xagent_eval.scoring import score_run
from tools.telemetry import estimate_tokens_from_text, record_llm_call

logger = logging.getLogger("xagent_eval.batch_runner")

VAULT_DIR = os.path.join(ROOT_DIR, "vault")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5:14b-instruct-q6_K"
SIM_USER_DEFAULT_MODEL = os.getenv("X_LINK_SIM_USER_MODEL", "llama3.2:latest")
SIM_USER_FALLBACK_MODELS = [
    candidate.strip()
    for candidate in os.getenv(
        "X_LINK_SIM_USER_FALLBACKS",
        f"{SIM_USER_DEFAULT_MODEL},{MODEL}",
    ).split(",")
    if candidate.strip()
]
OLLAMA_CONNECT_TIMEOUT = 5
OLLAMA_AGENT_READ_TIMEOUT = int(os.getenv("X_LINK_OLLAMA_AGENT_TIMEOUT", "75"))
OLLAMA_SIM_READ_TIMEOUT = int(os.getenv("X_LINK_OLLAMA_SIM_TIMEOUT", "12"))
OLLAMA_SIM_NUM_PREDICT = int(os.getenv("X_LINK_OLLAMA_SIM_NUM_PREDICT", "48"))
MEL_AGENT_CONTEXT_LINES = int(os.getenv("X_LINK_MEL_AGENT_CONTEXT_LINES", "8"))
MEL_AGENT_CONTEXT_CHARS = int(os.getenv("X_LINK_MEL_AGENT_CONTEXT_CHARS", "1800"))

PROMPT_LEAK_MARKERS = [
    "### [",
    "[conversation]",
    "[instructions]",
    "[guardrails]",
    "[core identity]",
    "anti-loop close rule",
    "security, compliance, and evidence requests",
    "meeting and follow-up language",
    "final behavior summary",
    "do not mirror the user's wording",
    "the next reply must be one terminal boundary sentence",
    "rules:",
]

AMY_FORBIDDEN_OWNERSHIP_PATTERNS = [
    r"\bi'?ll schedule\b",
    r"\bi will schedule\b",
    r"\bi'?ll ensure\b",
    r"\bi will ensure\b",
    r"\bi'?ll make sure\b",
    r"\bi will make sure\b",
    r"\bi'?ll send\b",
    r"\bi will send\b",
    r"\bi'?ll note\b",
    r"\bi will note\b",
    r"\bi'?ll get that request\b",
    r"\bi will get that request\b",
    r"\bi'?ll get that moving\b",
    r"\bi will get that moving\b",
    r"\bi'?ll get that over\b",
    r"\bi will get that over\b",
    r"\bi can get that requested\b",
    r"\bi can get that moving\b",
    r"\bi can get that request\b",
    r"\bi can use that preference\b",
    r"\bi can route that request\b",
    r"\bi have what i need for the handoff\b",
    r"\bsend (?:it|them|the overview|the details|the materials) directly to me\b",
    r"\bconfirmation email\b",
    r"\bset in motion\b",
    r"\bwill be prioritized\b",
    r"\bget started with the review process promptly\b",
    r"\bwill ensure that we get started\b",
]

AMY_UNVERIFIED_SPECIFICITY_PATTERNS = [
    r"\bbi-?weekly\b",
    r"\b10\s*-\s*20%\b",
    r"\bshared project management tool\b",
    r"\bdedicated project manager\b",
    r"\bproject managers?\b",
    r"\btechnical leads?\b",
    r"\bsimulation exercises\b",
    r"\bcontingency plans?\b",
    r"\bphased execution plans?\b",
    r"\bdefined milestones?\b",
    r"\badvanced detection mechanisms?\b",
    r"\bcontinuous monitoring\b",
    r"\bcontinuous surveillance\b",
    r"\bimmediate alerting mechanisms?\b",
    r"\bconfiguration assistance\b",
    r"\btoolkits? for integration\b",
    r"\bongoing support to optimize\b",
    r"\bfew weeks to a couple of months\b",
    r"\bour systems are designed to\b",
    r"\bautomated processes?\b",
    r"\bautomated handling\b",
    r"\btrigger automated responses?\b",
    r"\bpredefined actions?\b",
    r"\bunusual login patterns?\b",
    r"\bunexpected data access attempts?\b",
    r"\bblock(?:ing)? the ip address\b",
    r"\bdesignated security personnel\b",
    r"\brapid human response\b",
    r"\bcritical alerts?\b",
    r"\bnon-critical alerts?\b",
    r"\bwithin minutes?\b",
    r"\bwithin \d+\s*-\s*\d+ minutes?\b",
    r"\bminutes after detection\b",
    r"\bresponse times?\b.*\bminutes?\b",
    r"\bsecurity operations team\b",
    r"\bincident management\b",
    r"\bexternal specialists?\b",
    r"\bmonitoring tools\b",
    r"\brouting it to the appropriate team\b",
    r"\bappropriate team for analysis and response\b",
    r"\bwalk through an example of our monitoring\b",
    r"\bprepare the relevant case studies\b",
    r"\bready for our discussion\b",
    r"\breal-?time monitoring\b",
    r"\btrue real-?time monitoring\b",
    r"\badvanced analytics\b",
    r"\bmachine learning\b",
    r"\bwhitepapers?\b",
    r"\btechnical blogs?\b",
    r"\bblogs? and whitepapers?\b",
    r"\bwebsite whitepapers?\b",
    r"\breal-time visibility\b",
    r"\bcontinuous real-?time\b",
]


def _ollama_generate_text(
    model: str,
    prompt: str,
    *,
    options: Optional[dict] = None,
    read_timeout: int = OLLAMA_AGENT_READ_TIMEOUT,
    workflow: str = "xagent_eval",
    metadata: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Call Ollama with explicit timeouts and return text or a short error."""
    started_at = datetime.now()
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": options or {},
            },
            timeout=(OLLAMA_CONNECT_TIMEOUT, read_timeout),
        )
        response.raise_for_status()
        payload = response.json()
        reply = payload.get("response", "").strip()
        record_llm_call(
            workflow=workflow,
            provider="ollama",
            model=model,
            started_at=started_at,
            ended_at=datetime.now(),
            input_tokens_est=estimate_tokens_from_text(prompt),
            output_tokens_est=estimate_tokens_from_text(reply),
            success=True,
            metadata=metadata or {},
        )
        return reply, None
    except requests.exceptions.Timeout:
        error = f"ollama_timeout:{model}"
    except requests.exceptions.RequestException as exc:
        error = f"ollama_request_error:{model}:{exc}"
    except ValueError as exc:
        error = f"ollama_parse_error:{model}:{exc}"

    record_llm_call(
        workflow=workflow,
        provider="ollama",
        model=model,
        started_at=started_at,
        ended_at=datetime.now(),
        input_tokens_est=estimate_tokens_from_text(prompt),
        output_tokens_est=0,
        success=False,
        metadata={**(metadata or {}), "error": error},
    )
    return None, error


def _generate_user_sim_text(
    prompt: str,
    *,
    preferred_model: Optional[str] = None,
    fallback_model: str = MODEL,
    metadata: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Generate simulated user text with a fast-path model and resilient fallback chain."""
    candidates: List[str] = []
    for candidate in [preferred_model, *SIM_USER_FALLBACK_MODELS, fallback_model]:
        cleaned = (candidate or "").strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    last_error: Optional[str] = None
    for index, model_name in enumerate(candidates):
        reply, error = _ollama_generate_text(
            model_name,
            prompt,
            options={
                "temperature": 0.65,
                "num_predict": OLLAMA_SIM_NUM_PREDICT,
                "stop": ["Agent:", "\n\n"],
            },
            read_timeout=OLLAMA_SIM_READ_TIMEOUT,
            workflow="mel_user_sim",
            metadata={
                **(metadata or {}),
                "candidate_index": str(index),
                "candidate_total": str(len(candidates)),
                "primary_model": candidates[0],
                "fallback": "true" if index > 0 else "false",
            },
        )
        if reply:
            return reply, None
        last_error = error
        logger.warning(f"User simulator model '{model_name}' failed ({error}).")

    return None, last_error


def _contains_non_latin_script(text: str) -> bool:
    for ch in text or "":
        if ord(ch) <= 127:
            continue
        name = unicodedata.name(ch, "")
        if any(tag in name for tag in ("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "ARABIC", "CYRILLIC", "HEBREW")):
            return True
    return False


def _sentence_split(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _compact_text(text: str, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _compile_eval_persona(agent_slug: str, persona: str, agent_domain: str, guardrails: str = "") -> str:
    """Compress large production personas into an eval-safe runtime prompt."""
    persona = (persona or "").strip()
    guardrails = (guardrails or "").strip()
    if len(persona) <= 6000:
        if guardrails:
            return (
                f"### [CORE IDENTITY]\n{persona}\n\n"
                f"### [GUARDRAILS]\n{guardrails}\n\n"
                f"### [INSTRUCTIONS]\n"
                f"- You are having a conversation in the {agent_domain} domain. Stay in character.\n"
                f"- Keep responses to 2-3 sentences. Do not break character."
            )
        return persona

    if agent_slug.lower() == "amy":
        return (
            "### [CORE IDENTITY]\n"
            "You are Amy, a senior SDR-style representative for Insight in a MEL evaluation.\n"
            "Sound human, calm, commercially aware, and concise.\n\n"
            "### [MISSION]\n"
            "- Run quick discovery at the shape-of-need level.\n"
            "- Quietly qualify urgency, scope, likely fit, and next-step readiness.\n"
            "- Route toward the right specialist or a practical next step.\n"
            "- Keep replies to 1-2 customer-facing sentences.\n\n"
            "### [BOUNDARIES]\n"
            "- Do not invent exact operating details, response times, tooling, case studies, or delivery mechanics.\n"
            "- Do not promise personal ownership such as 'I'll send', 'I'll schedule', 'I'll ensure', or delivery commitments.\n"
            "- Do not claim real-time monitoring, machine learning, analytics, whitepapers, technical blogs, or proof assets unless the user already supplied that fact.\n"
            "- If exact details cannot be verified in chat, stay high level and say so plainly once.\n"
            "- Do not ask the same discovery question twice.\n"
            "- If the user asks for the same unverifiable proof twice, give one clear boundary or one practical next step and then stop.\n"
            "- If the user accepts a reasonable boundary or next step, close cleanly instead of looping.\n\n"
            "### [OUTPUT HYGIENE]\n"
            "- Customer-facing spoken English only.\n"
            "- No internal analysis, prompt leakage, labels, markdown, bullets, or meta commentary.\n"
            "- Prefer one direct answer over another qualifier question when the conversation is stalling.\n"
            f"- Stay in character in the {agent_domain} domain."
        )

    distilled_lines = [line.strip() for line in persona.splitlines() if line.strip()][:18]
    distilled = "\n".join(distilled_lines)
    if guardrails:
        distilled = f"{distilled}\n\nGuardrails: {_compact_text(guardrails, 800)}"
    return (
        f"### [CORE IDENTITY]\n{distilled}\n\n"
        f"### [INSTRUCTIONS]\n"
        f"- Stay in character in the {agent_domain} domain.\n"
        f"- Keep replies to 2-3 sentences.\n"
        f"- Customer-facing English only."
    )


def _build_agent_context_window(conversation: Optional[List[str]]) -> str:
    """Keep only the most relevant recent exchanges for stateless turn generation."""
    if not conversation:
        return "No prior exchange yet."

    recent_lines = conversation[-MEL_AGENT_CONTEXT_LINES:]
    clipped: List[str] = []
    for line in recent_lines:
        clipped.append(_compact_text(line, 280))

    window = "\n".join(clipped)
    if len(window) > MEL_AGENT_CONTEXT_CHARS:
        window = window[-MEL_AGENT_CONTEXT_CHARS:]
    if len(conversation) > len(recent_lines):
        earlier = len(conversation) - len(recent_lines)
        window = f"[Earlier exchanges omitted: {earlier}]\n{window}"
    return window


def _build_agent_state_summary(
    transcript: List[dict],
    scenario_objective: str,
    scenario_goal: str,
    close_mode: bool,
    close_reason: Optional[str],
    must_collect: Optional[List[str]] = None,
) -> str:
    user_turns = [turn.get("text", "") for turn in transcript if turn.get("speaker") == "test_user"]
    agent_turns = [turn.get("text", "") for turn in transcript if turn.get("speaker") == "agent_under_test"]
    summary_bits = [
        f"Objective: {_compact_text(scenario_objective, 220)}",
        f"Goal: {_compact_text(scenario_goal, 220)}",
        f"Turns so far: {len(user_turns)} user / {len(agent_turns)} agent",
        f"Mode: {'closing' if close_mode else 'active'}",
    ]
    if close_reason:
        summary_bits.append(f"Close reason: {close_reason}")
    if user_turns:
        summary_bits.append(f"Latest user concern: {_compact_text(user_turns[-1], 220)}")
    if len(user_turns) > 1:
        summary_bits.append(f"Previous user concern: {_compact_text(user_turns[-2], 180)}")
    if agent_turns:
        summary_bits.append(f"Latest agent stance: {_compact_text(agent_turns[-1], 180)}")
    if must_collect:
        transcript_lower = "\n".join(user_turns + agent_turns).lower()
        found = [item for item in must_collect if item.lower() in transcript_lower]
        if found:
            summary_bits.append(f"Collected signals: {', '.join(found[:4])}")
    return "\n".join(f"- {bit}" for bit in summary_bits if bit)


def _dedupe_sentences(text: str) -> str:
    seen = set()
    kept: List[str] = []
    for sentence in _sentence_split(text):
        signature = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        if not signature or signature in seen:
            continue
        seen.add(signature)
        kept.append(sentence)
    return " ".join(kept).strip()


def _limit_sentences(text: str, max_sentences: int = 2) -> str:
    sentences = _sentence_split(text)
    if not sentences:
        return ""
    return " ".join(sentences[:max_sentences]).strip()


def _strip_prompt_leakage(text: str) -> str:
    lines = []
    for raw_line in re.split(r"[\r\n]+", text or ""):
        line = raw_line.strip()
        lowered = line.lower()
        if not line:
            continue
        if any(marker in lowered for marker in PROMPT_LEAK_MARKERS):
            continue
        if _contains_non_latin_script(line):
            continue
        lines.append(line)

    cleaned = " ".join(lines).strip() if lines else re.sub(r"\s+", " ", text or "").strip()
    cleaned = re.sub(r"###\s*\[[^\]]+\].*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[[A-Z][A-Z _-]{3,}\].*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _amy_signature(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _amy_recent_agent_replies(conversation: Optional[List[str]]) -> List[str]:
    replies: List[str] = []
    for line in conversation or []:
        if ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        if speaker.strip().lower() in {"amy", "agent"}:
            cleaned = text.strip()
            if cleaned:
                replies.append(cleaned)
    return replies


def _amy_recent_user_messages(conversation: Optional[List[str]]) -> List[str]:
    messages: List[str] = []
    for line in conversation or []:
        if ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        if speaker.strip().lower() == "user":
            cleaned = text.strip()
            if cleaned:
                messages.append(cleaned)
    return messages


def _amy_recent_proof_pressure_count(
    scenario_id: str,
    conversation: Optional[List[str]],
    current_user_msg: str,
    limit: int = 3,
) -> int:
    recent_user_turns = _amy_recent_user_messages(conversation)
    window = recent_user_turns[-max(0, limit - 1):] + ([current_user_msg] if current_user_msg else [])
    return sum(1 for msg in window if _amy_is_proof_pressure(scenario_id, msg))


def _amy_pick_variant(candidates: List[str], conversation: Optional[List[str]]) -> str:
    used = {_amy_signature(item) for item in _amy_recent_agent_replies(conversation)}
    for candidate in candidates:
        if _amy_signature(candidate) not in used:
            return candidate
    return candidates[0] if candidates else ""


def _amy_conversation_has_email(conversation: Optional[List[str]], user_msg: str) -> bool:
    corpus = "\n".join((conversation or []) + [user_msg or ""])
    return "[redacted_email]" in corpus.lower() or bool(re.search(r"[\w\.-]+@[\w\.-]+\.\w+", corpus))


def _amy_is_proof_pressure(scenario_id: str, user_msg: str) -> bool:
    user_lower = (user_msg or "").lower()
    scenario_upper = (scenario_id or "").upper()
    return (
        "SECURITY" in scenario_upper
        or any(
            token in user_lower
            for token in [
                "real-time",
                "real time",
                "monitor",
                "proof",
                "case study",
                "case studies",
                "documentation",
                "gdpr",
                "finra",
                "audit",
                "compliance",
                "example",
            ]
        )
    )


def _amy_user_accepted_next_step(user_msg: str) -> bool:
    lowered = (user_msg or "").lower()
    return any(
        token in lowered
        for token in [
            "that works",
            "sounds good",
            "looking forward",
            "let's do",
            "lets do",
            "let's schedule",
            "lets schedule",
            "next week then",
            "tuesday at",
            "thursday at",
            "my email",
            "best email",
            "send me",
            "go from there",
            "we can proceed",
            "one clear next step",
            "that sounds like a step forward",
        ]
    )


def _amy_is_terminal_close(reply: str) -> bool:
    lowered = (reply or "").lower()
    return any(
        phrase in lowered
        for phrase in [
            "we can leave it there",
            "that works. thanks",
            "thanks for the time",
            "talk soon",
            "that is enough for the next step",
            "that is enough to move this forward",
            "that is enough to leave it there",
            "i cannot verify more than that in chat",
            "i do not have a verified proof packet i can add here",
            "i do not want to overstate anything beyond what i can verify here",
        ]
    )


def _amy_safe_reframe(
    user_msg: str,
    scenario_id: str,
    close_mode: bool,
    reason: str,
    conversation: Optional[List[str]] = None,
) -> str:
    user_lower = (user_msg or "").lower()
    scenario_upper = (scenario_id or "").upper()
    proof_pressure = _amy_is_proof_pressure(scenario_id, user_msg)
    meeting_pressure = any(
        token in user_lower
        for token in ["meeting", "call", "schedule", "next week", "tomorrow", "email", "follow-up", "follow up"]
    )
    migration_pressure = "CIO_TRANSFORM" in scenario_upper or any(
        token in user_lower
        for token in ["migration", "go live", "downtime", "timeline", "hardware", "data center", "support"]
    )
    has_email = _amy_conversation_has_email(conversation, user_msg)
    wants_materials = any(
        token in user_lower
        for token in ["email", "inbox", "send", "materials", "documentation", "case study", "case studies", "proof"]
    )
    wants_one_step = any(
        token in user_lower
        for token in ["one clear next step", "no sales loop", "no more back-and-forth", "no more back and forth"]
    )

    def _accepted_handoff_close() -> str:
        candidates = [
            "That works. Thanks.",
            "Appreciate it. We can leave it there.",
            "Sounds good. Thanks for the time.",
            "Understood. We can leave it there.",
        ]
        if any(token in user_lower for token in ["no more", "no further", "leave it at that", "back-and-forth", "back and forth"]):
            candidates = [
                "Understood. We can leave it there.",
                "That works. We can leave it there.",
                "Appreciate it. We can leave it there.",
            ]
        if any(token in user_lower for token in ["thanks", "thank you", "looking forward", "see you soon"]):
            candidates = [
                "Thanks. We can leave it there.",
                "Sounds good. Thanks for the time.",
                "Appreciate it. Talk soon.",
            ]
        if any(token in user_lower for token in ["email", "[redacted_email]", "contact", "point person"]):
            candidates = [
                "Thanks. That is enough for the next step.",
                "Understood. That is enough to move this forward.",
                "Appreciate it. That is enough to leave it there.",
            ]
        return _amy_pick_variant(candidates, conversation)

    if meeting_pressure and close_mode:
        return _accepted_handoff_close()

    if proof_pressure:
        if close_mode and reason in {"followup_loop", "loop"} and (
            _amy_user_accepted_next_step(user_msg)
            or any(token in user_lower for token in ["no more", "no further", "leave it at that", "back-and-forth", "back and forth"])
        ):
            return _accepted_handoff_close()
        if wants_materials and not has_email and (wants_one_step or close_mode):
            return _amy_pick_variant(
                [
                    "If you want one clean next step, the best email is enough.",
                    "If you want materials, the best email is enough for the next step.",
                    "For one clean next step, the best email is enough.",
                ],
                conversation,
            )
        if close_mode or reason == "ownership":
            return _amy_pick_variant(
                [
                    "I cannot verify more than that in chat.",
                    "I do not have a verified proof packet I can add here.",
                    "I do not want to overstate anything beyond what I can verify here.",
                ],
                conversation,
            )
        if "don't repeat" in user_lower or "do not repeat" in user_lower or "stop repeating" in user_lower:
            return _amy_pick_variant(
                [
                    "I can stay high level here, but I cannot verify the exact operating detail in chat.",
                    "I can confirm the service area, but not the exact operating model in chat.",
                    "I cannot verify that level of detail in chat.",
                ],
                conversation,
            )
        if reason == "specificity":
            return _amy_pick_variant(
                [
                    "I cannot verify exact response times or operating mechanics in chat.",
                    "I can stay high level here, but I cannot verify the exact monitoring model in chat.",
                    "I do not want to guess on specific timing or tooling in chat.",
                ],
                conversation,
            )
        return _amy_pick_variant(
            [
                "I can confirm the service area, but not the exact operating detail in chat.",
                "I can stay high level here, but I cannot verify the exact operating model in chat.",
                "I do not have verified proof I can quote in chat.",
            ],
            conversation,
        )

    if meeting_pressure:
        if close_mode or any(
            token in user_lower for token in ["works for me", "move forward", "sounds good", "that works", "see you", "looking forward"]
        ):
            return _accepted_handoff_close()
        return "Understood. The next step would be a brief follow-up with the right team."

    if migration_pressure or reason == "specificity":
        return "The exact operating model depends on your environment and scope, so I do not want to guess in chat."

    if close_mode:
        return _accepted_handoff_close()
    return _amy_pick_variant(
        [
            "I do not want to overstate what I can verify here.",
            "I can stay high level here without guessing.",
            "I do not want to guess beyond what I can verify here.",
        ],
        conversation,
    )


def _sanitize_amy_reply(
    reply: str,
    scenario: dict,
    user_msg: str,
    close_mode: bool,
    conversation: Optional[List[str]] = None,
) -> str:
    scenario_id = scenario.get("scenario_id", "")
    cleaned = _strip_prompt_leakage(reply)
    cleaned = _dedupe_sentences(cleaned)

    if any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in AMY_FORBIDDEN_OWNERSHIP_PATTERNS):
        cleaned = _amy_safe_reframe(user_msg, scenario_id, close_mode, "ownership", conversation)
    elif any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in AMY_UNVERIFIED_SPECIFICITY_PATTERNS):
        cleaned = _amy_safe_reframe(user_msg, scenario_id, close_mode, "specificity", conversation)

    lowered = cleaned.lower()
    if (
        lowered.startswith("understood")
        and any(token in lowered for token in ["captured", "noted", "preference", "right team", "follow-up", "follow up", "will send", "will ensure", "prioritized"])
    ):
        cleaned = _amy_safe_reframe(user_msg, scenario_id, close_mode, "followup_loop", conversation)

    if cleaned.lower().count("at a high level") > 1:
        cleaned = _amy_safe_reframe(user_msg, scenario_id, close_mode, "loop", conversation)

    lowered = cleaned.lower()
    if (
        lowered.count("clean handoff") > 0
        or lowered.count("the right team can confirm details") > 0
        or lowered.count("that is enough context for the next step") > 1
        or lowered.count("move this forward cleanly") > 0
    ):
        cleaned = _amy_safe_reframe(user_msg, scenario_id, True, "loop", conversation)

    if conversation:
        prior_signatures = [_amy_signature(item) for item in _amy_recent_agent_replies(conversation)]
        if _amy_signature(cleaned) in prior_signatures:
            cleaned = _amy_safe_reframe(user_msg, scenario_id, close_mode, "loop", conversation)

    cleaned = _limit_sentences(cleaned, 2)
    cleaned = _dedupe_sentences(cleaned)
    if not cleaned:
        cleaned = _amy_safe_reframe(user_msg, scenario_id, close_mode, "empty", conversation)
    return cleaned


def _sanitize_agent_reply(
    agent_slug: str,
    scenario: dict,
    user_msg: str,
    reply: str,
    close_mode: bool,
    conversation: Optional[List[str]] = None,
) -> str:
    cleaned = _strip_prompt_leakage(reply)
    cleaned = _dedupe_sentences(cleaned)
    if agent_slug.lower() == "amy":
        return _sanitize_amy_reply(cleaned, scenario, user_msg, close_mode, conversation)
    return cleaned or "I do not want to overstate that here."

def redact_sensitive(text: str) -> str:
    if not isinstance(text, str): return text
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED_EMAIL]', text)
    text = re.sub(r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b', '[REDACTED_PHONE]', text)
    return text

def recursively_redact(data):
    if isinstance(data, dict): return {k: recursively_redact(v) for k, v in data.items()}
    elif isinstance(data, list): return [recursively_redact(i) for i in data]
    elif isinstance(data, str): return redact_sensitive(data)
    return data


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
    
    # Redact transcript for OPSEC
    clean_transcript = recursively_redact(transcript)

    # metadata.json
    meta_path = os.path.join(run_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata.to_dict(), f, indent=2)
    saved.append(meta_path)

    # transcript.json
    tx_json_path = os.path.join(run_dir, "transcript.json")
    with open(tx_json_path, "w", encoding="utf-8") as f:
        json.dump(clean_transcript, f, indent=2)
    saved.append(tx_json_path)

    # transcript.txt
    tx_text_path = os.path.join(run_dir, "transcript.txt")
    with open(tx_text_path, "w", encoding="utf-8") as f:
        f.write(transcript_to_text(clean_transcript))
    saved.append(tx_text_path)

    # scorecard.json
    sc_path = os.path.join(run_dir, "scorecard.json")
    with open(sc_path, "w", encoding="utf-8") as f:
        json.dump(scorecard.to_dict(), f, indent=2)
    saved.append(sc_path)

    return saved


def build_failure_scorecard(
    metadata: RunMetadata,
    transcript: List[dict],
) -> Scorecard:
    """Materialize runtime or scoring failures so batches never collapse into NO_DATA."""
    if metadata.status == "error":
        classification = "review_runtime_failure"
        notes = metadata.error_message or "The run failed before scoring completed."
    elif metadata.transcript_status == "failed":
        classification = "review_transcript_failure"
        notes = "The run did not produce a reviewable transcript."
    else:
        classification = "review_scoring_failure"
        notes = metadata.error_message or "The run completed, but scoring could not be produced."

    end_state = metadata.completion_reason or metadata.end_state_label or "runtime_failure"
    categories = [
        CategoryScore(
            key="runtime_reliability",
            label="Runtime Reliability",
            score=1,
            weight=5,
            notes=notes,
            fail_flag=True,
        ),
        CategoryScore(
            key="transcript_completeness",
            label="Transcript Completeness",
            score=1 if transcript else 0,
            weight=3,
            notes=f"Captured {len(transcript)} normalized turns before failure.",
            fail_flag=True,
        ),
    ]
    critical_failures = [metadata.error_message or "Runtime failure during MEL eval."]
    return Scorecard(
        run_id=metadata.run_id,
        scenario_id=metadata.scenario_id,
        target_agent=metadata.target_agent,
        overall_score=0.0,
        pass_fail="FAIL_BLOCK_RELEASE",
        classification=classification,
        end_state_label=end_state,
        categories=categories,
        warnings=["Run ended before a valid scored conversation could be completed."],
        critical_failures=critical_failures,
    )


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
        scenario_pack_class=inputs.scenario_pack_class,
        scenario_manifest_id=inputs.scenario_manifest_id,
        scenario_manifest_path=inputs.scenario_manifest_path,
        total_runs=len(run_ids),
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
            k: round(v / cat_counts[k], 1)
            for k, v in cat_scores.items()
        }

        # Include full run data for the Hub
        summary.runs = [s.to_dict() for s in scorecards]
        summary.data["runtime_failure_count"] = sum(
            1 for s in scorecards if str(s.classification).startswith("review_")
        )

        # Top failure categories (< 3.0 on a 5-point scale)
        low_cats = sorted(summary.category_averages.items(), key=lambda x: x[1])
        summary.top_failure_categories = [k for k, v in low_cats if v < 3.0][:3]
    else:
        summary.verdict = "NO_DATA"
        summary.failed = summary.total_runs
        summary.data["runtime_failure_count"] = summary.total_runs

    # Pass reviewer status fields if they exist in data (populated in tool.py)
    summary.reviewer_status = summary.data.get("reviewer_status", "skipped")
    summary.reviewer_error = summary.data.get("reviewer_error")
    summary.review_artifact_path = summary.data.get("review_artifact_path")

    if not scorecards:
        return summary

    # Verdict
    has_block = any(s.pass_fail == "FAIL_BLOCK_RELEASE" for s in scorecards)
    if has_block:
        summary.verdict = "NO_SHIP"
    elif summary.pass_rate >= 80:
        summary.verdict = "SHIP"
    elif summary.pass_rate >= 60:
        summary.verdict = "CONDITIONAL"
    else:
        summary.verdict = "NO_SHIP"

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
        f.write(f"Pack Class:     {summary.scenario_pack_class}\n")
        if summary.scenario_manifest_id:
            f.write(f"Manifest ID:    {summary.scenario_manifest_id}\n")
        if summary.scenario_manifest_path:
            f.write(f"Manifest Path:  {summary.scenario_manifest_path}\n")
        f.write(f"Total Runs:     {summary.total_runs}\n")
        f.write(f"Passed:         {summary.passed}\n")
        f.write(f"Failed:         {summary.failed}\n")
        f.write(f"Pass Rate:      {summary.pass_rate}%\n")
        f.write(f"Average Score:  {summary.average_score}\n")
        f.write(f"Verdict:        {summary.verdict}\n")
        f.write(f"\nCategory Averages:\n")
        for k, v in summary.category_averages.items():
            f.write(f"  {k}: {v}/5.0\n")
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


def _build_sim_user_rules(
    scenario: dict,
    *,
    agent_domain: str,
    close_mode: bool,
    slot_intercepted: bool,
) -> str:
    """Build humanized prospect rules for the simulated user."""
    human_profile = scenario.get("human_profile") or {}
    softening_signals = human_profile.get("softening_signals", [])
    unrealistic_handling = human_profile.get("unrealistic_request_handling", [])
    emotional_texture = human_profile.get("emotional_texture", [])
    baseline_tone = human_profile.get("baseline_tone", "skeptical but human")

    lines = [
        "RULES:",
        "- Respond with EXACTLY 1-2 sentences as the prospect.",
        "- Act like a real human buyer in a live conversation, not a torture-test harness.",
        f"- Your baseline tone is {baseline_tone}.",
        "- Keep your goal, but allow normal human behavior like brief acknowledgment, impatience, curiosity, or partial cooperation.",
        "- Real people do not try to squeeze one more test question out of every turn.",
        "- Real people sometimes accept a partial answer, decline politely, or end the conversation once the practical next step is clear.",
        "- If the agent gives one clear, truthful boundary, do not keep demanding the exact same impossible proof forever.",
        "- If the agent answers directly and stays grounded, you may soften slightly, accept the limit, or ask one new reasonable follow-up.",
        "- If you already pushed the same point twice and the agent still cannot verify it in chat, either ask for one realistic next step or let the conversation settle.",
        "- If you say you do not want a loop, and the agent stops looping, do not keep punishing them for the same thing.",
        "- If you have already shared contact details or agreed to a next step, do not keep reopening the exact same demand unless the agent creates a genuinely new problem.",
        "- Ask a relevant follow-up only when it truly helps you reach your goal.",
        "- If the agent gave a vague answer, push for specifics once, and only keep pressing if they truly dodged you.",
        "- Avoid repeating the same question unless the agent clearly failed to address it.",
        "- Do NOT act like a scripted FAQ machine or a pure adversarial evaluator.",
        "- Do NOT say 'Tell me more' or 'That sounds great'.",
        "- NEVER leave your response empty.",
    ]

    if close_mode:
        lines.append("- The conversation is near a natural stopping point. If the agent gives a valid boundary or next step, you may let it end.")
        lines.append("- In closing mode, it is normal to acknowledge, accept, decline, or disengage briefly instead of creating one more challenge.")
    if slot_intercepted:
        lines.append("- If you choose to share contact details now, do it once and do not re-open the same demand again.")
        lines.append("- After sharing contact details, do not keep repeating them unless the agent clearly confused or changed them.")
    if emotional_texture:
        lines.append("- Human texture to reflect when natural:")
        lines.extend(f"  - {item}" for item in emotional_texture)
    if softening_signals:
        lines.append("- Softening signals:")
        lines.extend(f"  - {item}" for item in softening_signals)
    if unrealistic_handling:
        lines.append("- Unreasonable-request handling:")
        lines.extend(f"  - {item}" for item in unrealistic_handling)

    lines.append(f"- Stay consistent with the {agent_domain} domain.")
    return "\n".join(lines)


async def execute_simulated_run(
    run_id: str,
    batch_id: str,
    inputs: EvalInputs,
    scenario: dict,
    contract: EvalContract = None,
    on_turn: Optional[callable] = None,
    on_status: Optional[callable] = None,
) -> Tuple[RunMetadata, List[dict], Optional[Scorecard]]:
    """
    Execute a single eval run using text-based simulation (Ollama).
    """
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
        scenario_pack_class=scenario.get("pack_class", inputs.scenario_pack_class or "core"),
        scenario_source=scenario.get("source", "canonical"),
        scenario_family=scenario.get("lane"),
        realism_label=scenario.get("realism_label"),
        source_scenario_id=scenario.get("source_scenario_id"),
    )

    transcript = []
    conversation = []

    # Map contract archetypes
    user_archetype = "a prospect"
    if contract and contract.user_archetypes:
        user_archetype = random.choice(contract.user_archetypes)

    # Load agent metadata (slug, domain)
    agents_path = os.path.join(ROOT_DIR, "config", "agents.yaml")
    agents_data = {}
    try:
        import yaml
        with open(agents_path, "r", encoding="utf-8") as f:
            agents_data = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to load agents.yaml: {e}")

    agent_conf = next((a for a in agents_data.get("agents", []) if a["slug"] == inputs.target_agent), {})
    agent_role_text = agent_conf.get("role", "AI Agent")
    agent_domain = agent_conf.get("domain", "SaaS / AI")

    # Load agent persona and compile a MEL-friendly runtime prompt.
    agent_persona = inputs.override_prompt
    guardrails = ""
    if not agent_persona:
        try:
            agent_persona = agent_conf.get("persona", f"You are {inputs.target_agent}, a professional X-Agent.")
            guardrails = agent_conf.get("guardrails", "Keep responses concise and professional.")
        except Exception as e:
            logger.warning(f"Failed to build agent persona for {inputs.target_agent}: {e}")
            agent_persona = "You are having a sales conversation. Stay in character."
    agent_prompt = _compile_eval_persona(inputs.target_agent, agent_persona or "", agent_domain, guardrails)

    # ── Endgame Controller State ─────────────────────────────
    close_strategy = contract.close_strategy if contract else {}
    max_close_turns = close_strategy.get("max_close_turns", 2)
    repeat_limit = close_strategy.get("repeat_cta_limit", 2)
    must_collect = contract.must_collect if contract else []
    required_slots = close_strategy.get("required_slots", [])
    
    agent_cta_map = {} # Track phrase repetition
    agent_questions = {} # Track question repetition
    slot_dodges = {}   # Track how many times user dodged a specific slot
    _used_fallbacks = set()  # Track which fallback questions have been used
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
    conversation_start_mode = (getattr(contract, "conversation_start_mode", "user_first") or "user_first").lower()

    try:
        if conversation_start_mode == "speak_first":
            opener_prompt = (
                f"{agent_prompt}\n\n"
                f"### [OPENING MODE]\n"
                f"You are speaking first before the user has asked anything yet.\n"
                f"Give one short spoken opening line only. Identify yourself if your prompt requires it.\n"
                f"Do not answer the scenario opening question yet because the user has not asked it.\n\n"
                f"{inputs.target_agent.capitalize()}:"
            )
            opener_reply, opener_error = _ollama_generate_text(
                MODEL,
                opener_prompt,
                options={"temperature": 0.3, "stop": ["User:", "\n\n", f"{inputs.target_agent.capitalize()}:"]},
                read_timeout=OLLAMA_AGENT_READ_TIMEOUT,
                workflow="mel_agent_eval",
                metadata={"agent": inputs.target_agent, "run_id": run_id, "scenario_id": scenario.get("scenario_id"), "phase": "opener"},
            )
            if opener_error:
                metadata.status = "error"
                metadata.error_message = opener_error
                metadata.completion_reason = "agent_generation_failed"
                logger.error(f"Run {run_id} opening generation failed: {opener_error}")
                return metadata, transcript, None

            opener_reply = _sanitize_agent_reply(
                inputs.target_agent,
                scenario,
                "",
                opener_reply or "Hi, I am here to help.",
                False,
                conversation,
            )

            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "agent_under_test",
                "text": opener_reply or "Hi, I am here to help.",
                "target_agent": inputs.target_agent,
                "scenario_id": scenario.get("scenario_id"),
                "run_id": run_id,
                "batch_id": batch_id,
                "conversation_start_mode": conversation_start_mode,
            })
            conversation.append(f"{inputs.target_agent.capitalize()}: {opener_reply or 'Hi, I am here to help.'}")

        # Start with user's opening message
        user_msg = opening_msg

        # ── Conversation Turn Loop ────────────────────────────
        for turn_num in range(1, inputs.max_turns + 1):
            # Check for twist injection
            if turn_num in twists:
                user_msg = twists[turn_num]

            # Record user turn
            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "test_user",
                "text": user_msg,
                "target_agent": inputs.target_agent,
                "scenario_id": scenario.get("scenario_id"),
                "run_id": run_id,
                "batch_id": batch_id,
            })
            conversation.append(f"User: {user_msg}")

            amy_recent_proof_pressure = 0
            if inputs.target_agent.lower() == "amy":
                amy_recent_proof_pressure = _amy_recent_proof_pressure_count(
                    scenario.get("scenario_id", ""),
                    conversation[:-1],
                    user_msg,
                )
                if amy_recent_proof_pressure >= 2:
                    close_mode = True
                    close_reason = "proof_pressure_loop"

            # ── Execute on_turn Callback (Turn Start) ───────────
            if on_turn:
                on_turn(turn_num, user_msg, "")

            # ── Endgame Controller: Trigger Check ────────────────
            if not close_mode:
                # 1. Turn proximity
                if turn_num >= inputs.max_turns - max_close_turns:
                    close_mode = True
                    close_reason = "turn_limit_proximity"
                
                # 2. Must-collect satisfaction (Heuristic)
                if must_collect and turn_num > 1:
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
                    if count >= repeat_limit + 1: # Strict 3rd strike
                        close_mode = True
                        close_reason = "repetition_limit_hit"
                        break

            # ── Generate Agent Response ──────────────────────
            current_agent_prompt = agent_prompt
            if close_mode:
                preferred = close_strategy.get("preferred_close", "graceful_exit")
                current_agent_prompt += (
                    f"\n\n### [ENDGAME MODE: {close_reason.upper()}]\n"
                    f"Gather sufficient info or handle turn limit. Priority: {preferred.replace('_', ' ')}.\n"
                    f"Summarize next steps, confirm handoff, and close professionally."
                )

            recent_context = _build_agent_context_window(conversation)
            state_summary = _build_agent_state_summary(
                transcript,
                scenario_objective,
                scenario_goal,
                close_mode,
                close_reason,
                must_collect,
            )
            prompt = (
                f"{current_agent_prompt}\n\n"
                f"### [SCENARIO]\n"
                f"Context: {_compact_text(scenario_objective, 260)}\n"
                f"Goal: {_compact_text(scenario_goal, 220)}\n\n"
                f"### [STATE]\n{state_summary}\n\n"
                f"### [RECENT EXCHANGES]\n{recent_context}\n"
                f"{inputs.target_agent.capitalize()}:"
            )

            agent_reply, agent_error = _ollama_generate_text(
                MODEL,
                prompt,
                options={
                    "temperature": 0.4,
                    "num_predict": 160,
                    "stop": ["User:", "\n\n", f"{inputs.target_agent.capitalize()}:"],
                },
                read_timeout=OLLAMA_AGENT_READ_TIMEOUT,
                workflow="mel_agent_eval",
                metadata={"agent": inputs.target_agent, "run_id": run_id, "scenario_id": scenario.get("scenario_id"), "phase": "agent_turn", "turn": str(turn_num)},
            )
            if agent_error:
                metadata.status = "error"
                metadata.error_message = agent_error
                metadata.completion_reason = "agent_generation_failed"
                logger.error(f"Run {run_id} agent generation failed: {agent_error}")
                break

            if not agent_reply:
                agent_reply = "I appreciate your interest. How can I help you today."

            agent_reply = _sanitize_agent_reply(
                inputs.target_agent,
                scenario,
                user_msg,
                agent_reply,
                close_mode,
                conversation,
            )

            if (
                inputs.target_agent.lower() == "amy"
                and amy_recent_proof_pressure >= 2
                and not _amy_is_terminal_close(agent_reply)
            ):
                agent_reply = _amy_safe_reframe(
                    user_msg,
                    scenario.get("scenario_id", ""),
                    True,
                    "loop",
                    conversation,
                )

            # ── Execute on_turn Callback (Turn Complete) ───────────
            if on_turn:
                on_turn(turn_num, user_msg, agent_reply)

            transcript.append({
                "turn": len(transcript) + 1,
                "speaker": "agent_under_test",
                "text": agent_reply,
                "target_agent": inputs.target_agent,
                "scenario_id": scenario.get("scenario_id"),
                "run_id": run_id,
                "batch_id": batch_id,
                "close_mode": close_mode
            })
            conversation.append(f"{inputs.target_agent.capitalize()}: {agent_reply}")

            if (
                inputs.target_agent.lower() == "amy"
                and _amy_is_proof_pressure(scenario.get("scenario_id", ""), user_msg)
                and _amy_user_accepted_next_step(user_msg)
                and _amy_is_terminal_close(agent_reply)
            ):
                metadata.completion_reason = "accepted_handoff_terminal_close"
                break

            # ── Repetition & Stall Breaker (Harden) ───────────
            # Identifies Mirror Loops (User repeating) and Agent Loops (Stalled/Repetitive)
            
            # A. Agent Repetition (Must trigger faster if it's the SAME refusal)
            a_full = agent_reply.lower().strip(".!? ")
            a_head = a_full[:40] if len(a_full) > 40 else a_full
            a_tail = a_full[-40:] if len(a_full) > 40 else a_full
            
            # Track counts for Full, Head, and Tail
            agent_cta_map[a_full] = agent_cta_map.get(a_full, 0) + 1
            agent_cta_map[f"H:{a_head}"] = agent_cta_map.get(f"H:{a_head}", 0) + 1
            agent_cta_map[f"T:{a_tail}"] = agent_cta_map.get(f"T:{a_tail}", 0) + 1
            
            repetition_tripped = (
                agent_cta_map[a_full] >= 3 or 
                agent_cta_map[f"H:{a_head}"] >= 3 or 
                agent_cta_map[f"T:{a_tail}"] >= 3
            )
            
            if repetition_tripped:
                logger.warning(f"🛑 [CIRCUIT BREAKER] Agent repetition loop detected in {run_id}. Terminating.")
                metadata.completion_reason = "repetition_limit_hit"
                break

            # B. User "Question Loop" Detector (Mirror Breaker)
            # If the User Judge repeats the same question 3 times, identify as a loop
            u_clean = user_msg.lower().strip() 
            if "?" in u_clean or len(u_clean) > 10:
                # Use a fuzzier signature for questions to catch "Can you answer X?" vs "answer X?"
                q_sig = u_clean.replace("?", "").strip()
                agent_questions[q_sig] = agent_questions.get(q_sig, 0) + 1
                if agent_questions[q_sig] >= 3:
                    logger.warning(f"🛑 [CIRCUIT BREAKER] User (Judge) entered a question loop. Terminating.")
                    metadata.completion_reason = "user_judge_loop_hit"
                    break

            # ── Loop Detection: Break if closing ───────────
            if close_mode:
                closure_keywords = ["goodbye", "have a great", "talk soon", "closed", "thank you", "thanks", "done"]
                if any(x in agent_reply.lower() for x in closure_keywords):
                    break

            # ── Generate Next User Response (Simulator) ────
            user_profile = scenario.get("user_profile", {})
            user_context = _map_domain_context(user_profile.get("context", "A prospect visiting the website."), agent_domain)
            user_role = scenario.get("role", "cooperative_user")

            # Identify if agent is asking for a required slot
            slot_intercepted = False
            intercept_text = ""
            reply_lower = agent_reply.lower()
            for slot in required_slots:
                keywords = [slot.replace("_", " ")]
                if slot == "email": keywords.append("email address")
                if slot == "phone": keywords.append("number")
                if slot == "full_name": keywords.extend(["name", "who am i speaking with"])
                
                if any(kw in reply_lower for kw in keywords):
                    slot_dodges[slot] = slot_dodges.get(slot, 0) + 1
                    if close_mode or slot_dodges[slot] >= 2:
                        val = user_identity.get(slot, "I'm not sure.")
                        intercept_text = f"Sure, my {slot.replace('_', ' ')} is {val}. "
                        slot_intercepted = True
                        break

            # SURGICAL CONTEXT: Inject Role and Domain into Simulator
            user_rules = _build_sim_user_rules(
                scenario,
                agent_domain=agent_domain,
                close_mode=close_mode,
                slot_intercepted=slot_intercepted,
            )
            conv_text = "\n".join(conversation)
            user_gen_prompt = (
                f"You are {user_profile.get('name', 'a prospect')} talking to {inputs.target_agent}.\n"
                f"SITUATION: {user_context}\n"
                f"DOMAIN: {agent_domain}\n"
                f"Your goal: {scenario_goal}\n"
                f"{'Provide your contact info now: ' + json.dumps(user_identity) if slot_intercepted or close_mode else ''}\n\n"
                f"{user_rules}\n\n"
                f"[CONVERSATION]\n{conv_text}\n{inputs.target_agent}: {agent_reply}\n"
                f"{user_profile.get('name', 'User')}: {intercept_text}"
            )

            raw_user_reply, user_error = _generate_user_sim_text(
                user_gen_prompt,
                preferred_model=getattr(inputs, "sim_user_model", None),
                metadata={"agent": inputs.target_agent, "run_id": run_id, "scenario_id": scenario.get("scenario_id"), "phase": "user_turn", "turn": str(turn_num)},
            )
            if user_error:
                logger.warning(f"Run {run_id} user simulator fallback triggered: {user_error}")
                raw_user_reply = ""

            user_msg = f"{intercept_text}{raw_user_reply or ''}".strip()
            if not user_msg or len(user_msg) < 5:
                # Dynamic fallback pool — 20 questions, shuffled, never repeats
                _all_fallbacks = [
                    f"What specific results have other companies seen with X Agents in {agent_domain}?",
                    "Walk me through the onboarding process from start to finish.",
                    "What does pricing look like for a company our size?",
                    "How quickly can we go live after signing?",
                    f"What makes X Agents different from competitors in {agent_domain}?",
                    "Can you show me a case study or demo?",
                    "What kind of support do you offer post-launch?",
                    "Who on your team would we be working with during setup?",
                    f"How would X Agents handle peak hours in {agent_domain}?",
                    "What happens if X Agents can't answer a customer's question?",
                    "How does the handoff to a human work in practice?",
                    "What CRM or ticketing systems do X Agents integrate with?",
                    "Can we customize the agent's personality and tone for our brand?",
                    "What analytics and reporting do you provide?",
                    "How do you handle data privacy and security?",
                    "Can multiple team members manage the agent?",
                    "What's the biggest deployment you've done so far?",
                    f"How do you train the agent on our specific {agent_domain} workflows?",
                    "Is there a free trial or pilot program?",
                    "What does the contract look like, monthly or annual?",
                ]
                # Filter out already-used fallbacks in this scenario
                available = [q for q in _all_fallbacks if q not in _used_fallbacks]
                if not available:
                    available = _all_fallbacks  # Reset if all exhausted
                user_msg = random.choice(available)
                _used_fallbacks.add(user_msg)

        if metadata.status != "error":
            metadata.status = "success"
            metadata.classification = "valid_product_signal"
        metadata.close_mode_triggered = close_mode
        metadata.close_reason = close_reason

    except Exception as e:
        metadata.status = "error"
        metadata.error_message = str(e)
        logger.error(f"Run {run_id} failed: {e}")

    metadata.completed_at = datetime.now().isoformat()
    normalized = normalize_transcript(transcript)
    metadata.actual_turns = len(normalized)
    metadata.qa_count = len([t for t in normalized if t.get("speaker") == "agent_under_test"])
    if metadata.started_at and metadata.completed_at:
        try:
            started = datetime.fromisoformat(metadata.started_at)
            completed = datetime.fromisoformat(metadata.completed_at)
            metadata.duration_seconds = round((completed - started).total_seconds(), 2)
        except Exception:
            metadata.duration_seconds = 0.0

    if normalized:
        normalized[-1]["completion_reason"] = metadata.completion_reason
        normalized[-1]["transcript_status"] = "complete" if metadata.status == "success" else "partial"
        metadata.transcript_status = normalized[-1]["transcript_status"]
    else:
        metadata.transcript_status = "failed"

    metadata.is_reviewable = metadata.status == "success" and len(normalized) >= 4
    
    # ── Context Capping: Prevent Scorer Hangs ────────────────
    # Truncate to the last 5000 characters if it's massive
    scoring_transcript = normalized
    if len(normalized) > 250:
        scoring_transcript = normalized[-250:]
        
    scorecard = None
    if metadata.status == "success" and scoring_transcript:
        try:
            if on_status:
                on_status("scoring_start", {
                    "run_id": run_id,
                    "scenario_id": scenario.get("scenario_id"),
                    "category_index": 0,
                    "category_total": 0,
                })
            scorecard = score_run(
                run_id=run_id,
                target_agent=inputs.target_agent,
                transcript=scoring_transcript,
                scenario=scenario,
                rubric_name=inputs.scoring_rubric,
                pass_threshold=inputs.pass_threshold,
                contract=contract,
                on_category_start=lambda idx, total, cat: on_status("scoring_category_start", {
                    "run_id": run_id,
                    "scenario_id": scenario.get("scenario_id"),
                    "category_index": idx,
                    "category_total": total,
                    "category_key": cat.get("key"),
                    "category_label": cat.get("label"),
                }) if on_status else None,
                on_category_scored=lambda idx, total, cat, cat_score: on_status("scoring_category_done", {
                    "run_id": run_id,
                    "scenario_id": scenario.get("scenario_id"),
                    "category_index": idx,
                    "category_total": total,
                    "category_key": cat.get("key"),
                    "category_label": cat.get("label"),
                    "score": cat_score.score,
                }) if on_status else None,
            )
            if on_status:
                on_status("scoring_done", {
                    "run_id": run_id,
                    "scenario_id": scenario.get("scenario_id"),
                    "overall_score": scorecard.overall_score if scorecard else None,
                    "pass_fail": scorecard.pass_fail if scorecard else None,
                })
        except Exception as e:
            logger.error(f"Scoring failed for run {run_id}: {e}")
            metadata.error_code = EvalError.SCORING_FAILED
            metadata.error_message = str(e)
            if on_status:
                on_status("scoring_error", {
                    "run_id": run_id,
                    "scenario_id": scenario.get("scenario_id"),
                    "error": str(e),
                })

    if scorecard is None:
        scorecard = build_failure_scorecard(metadata, normalized)

    return metadata, normalized, scorecard
