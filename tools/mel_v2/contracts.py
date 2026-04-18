from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class ConversationContract:
    start_mode: str = "user_first"
    required_identity: str = ""
    max_agent_questions: int = 3
    ask_email_only_when_requested: bool = True
    allowed_contact_triggers: List[str] = field(default_factory=list)
    forbidden_claim_phrases: List[str] = field(default_factory=list)
    expected_good_outcomes: List[str] = field(default_factory=list)
    hard_fail_conditions: List[str] = field(default_factory=list)
    fallback_questions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_mode": self.start_mode,
            "required_identity": self.required_identity,
            "max_agent_questions": self.max_agent_questions,
            "ask_email_only_when_requested": self.ask_email_only_when_requested,
            "allowed_contact_triggers": list(self.allowed_contact_triggers),
            "forbidden_claim_phrases": list(self.forbidden_claim_phrases),
            "expected_good_outcomes": list(self.expected_good_outcomes),
            "hard_fail_conditions": list(self.hard_fail_conditions),
            "fallback_questions": list(self.fallback_questions),
            "metadata": dict(self.metadata),
        }


def compile_contract(agent_slug: str, agent_config: Dict[str, Any], scenario: Dict[str, Any]) -> ConversationContract:
    persona = agent_config.get("persona", "") or ""
    opening_message = (scenario.get("opening_message") or "").strip()
    lower_persona = persona.lower()

    start_mode = "user_first" if opening_message else "agent_first"
    if "speak first" in lower_persona and not opening_message:
        start_mode = "agent_first"

    required_identity = ""
    if "danny from ai fusion labs" in lower_persona:
        required_identity = "Danny from AI Fusion Labs"
    elif "from ai fusion labs" in lower_persona and agent_config.get("name"):
        required_identity = f"{agent_config['name']} from AI Fusion Labs"

    max_agent_questions = 3
    if "one question per turn" in lower_persona:
        max_agent_questions = 6

    allowed_contact_triggers = [
        "demo",
        "case study",
        "examples",
        "pricing details",
        "send",
        "reach out",
        "contact me",
        "follow up",
    ]

    forbidden_claim_phrases = [
        "free trial",
        "pilot program",
        "monthly or annual",
        "dedicated implementation specialist",
        "dedicated team",
        "seamlessly",
        "experience x agents firsthand",
        "knowledge bank",
        "definitely",
        "absolutely",
        "no lag",
    ]

    fallback_questions = list(scenario.get("fallback_questions") or [])
    if not fallback_questions:
        for twist in scenario.get("twists", []):
            injection = (twist or {}).get("injection")
            if injection:
                fallback_questions.append(injection.strip())
    if agent_slug == "dani":
        deterministic_regression = [
            "We get a lot of remote buyers and peak traffic matters to us. How would this hold up under heavier demand?",
            "How do you handle data privacy and security?",
            "Can you show me a case study or demo?",
            "What does pricing look like for a company our size?",
        ]
        for candidate in deterministic_regression:
            if candidate not in fallback_questions:
                fallback_questions.append(candidate)

    return ConversationContract(
        start_mode=start_mode,
        required_identity=required_identity,
        max_agent_questions=max_agent_questions,
        ask_email_only_when_requested=True,
        allowed_contact_triggers=allowed_contact_triggers,
        forbidden_claim_phrases=forbidden_claim_phrases,
        expected_good_outcomes=list(scenario.get("expected_good_outcomes") or []),
        hard_fail_conditions=list(scenario.get("hard_fail_conditions") or []),
        fallback_questions=fallback_questions,
        metadata={
            "agent_slug": agent_slug,
            "scenario_id": scenario.get("scenario_id", ""),
            "scenario_title": scenario.get("title", ""),
        },
    )
