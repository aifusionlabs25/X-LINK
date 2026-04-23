import json
import logging
import os
import random
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
VAULT_DIR = ROOT_DIR / "vault"
MEL_DIR = VAULT_DIR / "mel"
SCENARIOS_DIR = ROOT_DIR / "config" / "eval_scenarios"
RUNTIME_CONFIG_PATH = ROOT_DIR / "config" / "sloane_runtime.yaml"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

logger = logging.getLogger("hermes_mel")


def _load_runtime_config() -> Dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    with RUNTIME_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_yaml_pack(pack_name: str) -> Dict[str, Any]:
    path = SCENARIOS_DIR / f"{pack_name}.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _get_pack_scenarios(pack_name: str) -> List[Dict[str, Any]]:
    return list((_load_yaml_pack(pack_name).get("scenarios") or []))


def _list_recent_batch_summaries(agent_slug: str, limit: int = 8) -> List[Dict[str, Any]]:
    batches_dir = VAULT_DIR / "evals" / "batches"
    if not batches_dir.exists():
        return []

    summaries: List[Dict[str, Any]] = []
    for batch_dir in batches_dir.iterdir():
        summary_path = batch_dir / "batch_summary.json"
        if not summary_path.exists():
            continue
        try:
            with summary_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if data.get("target_agent") != agent_slug:
            continue
        summaries.append(data)

    summaries.sort(key=lambda item: str(item.get("batch_id") or ""), reverse=True)
    return summaries[:limit]


def _derive_focus_signals(agent_slug: str) -> Dict[str, Any]:
    summaries = _list_recent_batch_summaries(agent_slug)
    failure_counter: Counter[str] = Counter()
    category_values: Dict[str, List[float]] = {}

    for summary in summaries:
        for key in summary.get("top_failure_categories") or []:
            failure_counter[key] += 1
        for key, value in (summary.get("category_averages") or {}).items():
            try:
                category_values.setdefault(key, []).append(float(value))
            except (TypeError, ValueError):
                continue

    weakest = [
        {
            "category": key,
            "mentions": count,
            "average": round(sum(category_values.get(key, [])) / max(len(category_values.get(key, [])), 1), 2),
        }
        for key, count in failure_counter.most_common(4)
    ]
    return {
        "recent_batch_count": len(summaries),
        "weakest_categories": weakest,
        "top_failure_categories": [item["category"] for item in weakest],
    }


def _hermes_api_payload(messages: List[Dict[str, str]]) -> Optional[str]:
    runtime_cfg = (_load_runtime_config().get("runtime") or {}).get("providers", {}).get("hermes_api", {}) or {}
    if not runtime_cfg.get("enabled"):
        return None

    base_url = str(runtime_cfg.get("base_url") or "").rstrip("/")
    if not base_url:
        return None

    headers = {"Content-Type": "application/json"}
    api_key = str(runtime_cfg.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        health = requests.get(f"{base_url}/v1/models", headers=headers, timeout=3)
        if health.status_code != 200:
            return None
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json={
                "model": runtime_cfg.get("model", "hermes-agent"),
                "messages": messages,
                "temperature": 0.4,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception as exc:
        logger.warning("Hermes adaptive generation unavailable, falling back: %s", exc)
        return None


def _ollama_json_generation(prompt: str, model: str = "qwen2.5:14b-instruct-q6_K") -> Optional[str]:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_predict": 1200,
                },
            },
            timeout=(3, 8),
        )
        response.raise_for_status()
        return (response.json().get("response") or "").strip()
    except Exception as exc:
        logger.warning("Ollama adaptive generation unavailable, using deterministic fallback: %s", exc)
        return None


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(raw_text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _build_generation_prompt(
    agent_slug: str,
    pack_name: str,
    base_scenarios: List[Dict[str, Any]],
    count: int,
    difficulty: str,
    focus_signals: Dict[str, Any],
) -> str:
    scenario_examples = []
    for scenario in base_scenarios[: min(3, len(base_scenarios))]:
        scenario_examples.append(
            {
                "scenario_id": scenario.get("scenario_id"),
                "title": scenario.get("title"),
                "difficulty": scenario.get("difficulty"),
                "opening_message": scenario.get("opening_message"),
                "human_profile": scenario.get("human_profile", {}),
                "tags": scenario.get("tags", []),
            }
        )

    domain_bias = ""
    if agent_slug.lower() == "amy":
        domain_bias = (
            "Amy is a frontline Insight SDR. Most scenarios should reflect normal enterprise discovery, migration, refresh, procurement, "
            "or high-level managed-services fit conversations.\n"
            "Deep security, compliance, or proof-pressure exchanges belong in a minority stress lane, not the default scenario mix.\n"
            "When difficulty is cooperative or mixed, prefer broad business conversations over specialist-level security interrogation.\n"
        )
    elif agent_slug.lower() == "evan":
        domain_bias = (
            "Evan is a premium moving intake specialist for Mullins Moving. ALL scenarios MUST stay strictly within the Moving & Logistics domain.\n"
            "Do NOT synthesize scenarios involving SaaS, AI software, data centers, or cybersecurity.\n"
            "Focus on residential/commercial moves, inventory discovery, packing services, timing, and specialty item handling.\n"
            "High difficulty should involve complex moving objections (pricing, insurance, scheduling constraints), not domain drift into tech/IT.\n"
        )

    return (
        "You are Hermes, the adaptive scenario architect for MEL 2.0.\n"
        "Generate realistic, human, sales-oriented evaluation scenarios as strict JSON.\n"
        "Do not create courtroom-style torture tests. Preserve buyer realism, pacing, and organic evolution.\n"
        "Return ONLY valid JSON with this shape:\n"
        "{\n"
        '  "scenarios": [\n'
        "    {\n"
        '      "title": "...",\n'
        '      "difficulty": "...",\n'
        '      "opening_message": "...",\n'
        '      "lane": "...",\n'
        '      "pressure_level": "low|medium|high",\n'
        '      "realism_label": "live_like|mixed|red_team",\n'
        '      "human_profile": {\n'
        '        "baseline_tone": "...",\n'
        '        "emotional_texture": ["..."],\n'
        '        "softening_signals": ["..."],\n'
        '        "unrealistic_request_handling": ["..."]\n'
        "      },\n"
        '      "expected_good_outcomes": ["..."],\n'
        '      "hard_fail_conditions": ["..."],\n'
        '      "tags": ["..."]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"{domain_bias}\n"
        f"Target agent: {agent_slug}\n"
        f"Canonical pack: {pack_name}\n"
        f"Requested count: {count}\n"
        f"Difficulty posture: {difficulty}\n"
        f"Recent failure signals: {json.dumps(focus_signals, ensure_ascii=True)}\n"
        f"Canonical examples: {json.dumps(scenario_examples, ensure_ascii=True)}\n"
    )


def _fallback_adaptive_scenarios(
    agent_slug: str,
    pack_name: str,
    base_scenarios: List[Dict[str, Any]],
    count: int,
    difficulty: str,
    focus_signals: Dict[str, Any],
) -> List[Dict[str, Any]]:
    weak_categories = focus_signals.get("top_failure_categories") or []
    difficulty_map = {
        "cooperative": ("live_like", "low"),
        "mixed": ("live_like", "medium"),
        "skeptical": ("mixed", "medium"),
        "frustrated": ("mixed", "high"),
        "adversarial": ("red_team", "high"),
    }
    realism_label, pressure_level = difficulty_map.get(str(difficulty).lower(), ("mixed", "medium"))

    defaults = [
        {
            "lane": "discovery",
            "opening_prefix": "I am interested, but I need to understand how this would work in our environment without turning this into a long procurement loop.",
        },
        {
            "lane": "credibility",
            "opening_prefix": "I have heard polished pitches before, so I need a grounded answer that sounds like it comes from someone who actually understands our world.",
        },
        {
            "lane": "next_step",
            "opening_prefix": "I do not need a script. I need to know whether there is a credible next step here or whether this is going to turn into another generic sales cycle.",
        },
    ]

    generated: List[Dict[str, Any]] = []
    pool = list(base_scenarios) or [{}]
    if agent_slug.lower() == "amy" and str(difficulty).lower() in {"cooperative", "mixed", "skeptical"}:
        preferred = [
            scenario
            for scenario in pool
            if "security" not in [str(tag).lower() for tag in (scenario.get("tags") or [])]
            and str(scenario.get("realism_label") or "live_like").lower() != "red_team"
            and str(scenario.get("difficulty") or "medium").lower() != "hard"
        ]
        if preferred:
            pool = preferred
    for idx in range(count):
        template = defaults[idx % len(defaults)]
        source = pool[idx % len(pool)]
        source_title = source.get("title", "Adaptive Scenario")
        scenario_id = f"HERMES_{agent_slug.upper()}_{uuid.uuid4().hex[:8].upper()}"
        focus_line = ""
        if weak_categories:
            focus_line = f" The interaction should quietly pressure {weak_categories[idx % len(weak_categories)].replace('_', ' ')} without becoming robotic."

        opening = (
            f"{template['opening_prefix']} {source.get('opening_message', '').strip()}".strip()
            + focus_line
        )

        generated.append(
            {
                "scenario_id": scenario_id,
                "title": f"Hermes Adaptive — {source_title}",
                "role": source.get("role", "buyer"),
                "difficulty": source.get("difficulty", "medium"),
                "opening_message": opening,
                "user_profile": source.get("user_profile", {}),
                "human_profile": {
                    "baseline_tone": "professional, skeptical, but still human",
                    "emotional_texture": [
                        "The prospect should sound like someone balancing risk, curiosity, and limited time.",
                        "If the agent gives one grounded answer and one realistic next step, the buyer can soften rather than escalating automatically.",
                    ],
                    "softening_signals": [
                        "Acknowledge one useful answer before pushing again.",
                        "Let the conversation evolve instead of repeating the same pressure line forever.",
                    ],
                    "unrealistic_request_handling": [
                        "Do not force the exact same proof request more than twice unless the agent keeps dodging.",
                        "If a practical next step is already clear, allow the exchange to wind down like a real buyer would.",
                    ],
                },
                "objectives": list(source.get("objectives") or []),
                "twists": list(source.get("twists") or []),
                "expected_good_outcomes": list(source.get("expected_good_outcomes") or []),
                "hard_fail_conditions": list(source.get("hard_fail_conditions") or []),
                "tags": list(set((source.get("tags") or []) + ["hermes_adaptive", template["lane"], realism_label])),
                "lane": template["lane"],
                "pressure_level": pressure_level,
                "realism_label": realism_label,
                "source": "hermes_adaptive",
                "source_pack": pack_name,
                "source_scenario_id": source.get("scenario_id"),
                "provenance": {
                    "generator": "hermes_fallback",
                    "created_at": datetime.now().isoformat(),
                    "focus_categories": weak_categories,
                },
            }
        )
    return generated


def generate_adaptive_scenarios(
    agent_slug: str,
    pack_name: str,
    count: int,
    difficulty: str = "mixed",
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    base_scenarios = _get_pack_scenarios(pack_name)
    focus_signals = _derive_focus_signals(agent_slug)
    prompt = _build_generation_prompt(agent_slug, pack_name, base_scenarios, count, difficulty, focus_signals)
    messages = [
        {
            "role": "system",
            "content": "You are Hermes. Return only valid JSON.",
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    raw = _hermes_api_payload(messages)
    if not raw:
        raw = _ollama_json_generation(prompt)

    parsed = _extract_json_object(raw or "")
    scenarios = list((parsed or {}).get("scenarios") or [])
    if not scenarios:
        scenarios = _fallback_adaptive_scenarios(agent_slug, pack_name, base_scenarios, count, difficulty, focus_signals)

    rng = random.Random(seed)
    normalized: List[Dict[str, Any]] = []
    for idx, scenario in enumerate(scenarios[:count]):
        source = base_scenarios[idx % len(base_scenarios)] if base_scenarios else {}
        normalized.append(
            {
                "scenario_id": scenario.get("scenario_id") or f"HERMES_{agent_slug.upper()}_{uuid.uuid4().hex[:8].upper()}",
                "title": scenario.get("title") or f"Hermes Adaptive — {source.get('title', 'Scenario')}",
                "role": scenario.get("role") or source.get("role", "buyer"),
                "difficulty": scenario.get("difficulty") or source.get("difficulty", "medium"),
                "opening_message": scenario.get("opening_message") or source.get("opening_message", "Tell me how this helps."),
                "user_profile": source.get("user_profile", {}),
                "human_profile": scenario.get("human_profile") or source.get("human_profile", {}),
                "objectives": list(source.get("objectives") or []),
                "twists": list(source.get("twists") or []),
                "expected_good_outcomes": scenario.get("expected_good_outcomes") or source.get("expected_good_outcomes", []),
                "hard_fail_conditions": scenario.get("hard_fail_conditions") or source.get("hard_fail_conditions", []),
                "tags": list(set((scenario.get("tags") or []) + ["hermes_adaptive"])),
                "lane": scenario.get("lane") or "discovery",
                "pressure_level": scenario.get("pressure_level") or "medium",
                "realism_label": scenario.get("realism_label") or "live_like",
                "source": "hermes_adaptive",
                "source_pack": pack_name,
                "source_scenario_id": source.get("scenario_id"),
                "provenance": {
                    "generator": "hermes_api" if raw and _extract_json_object(raw or "") else "hermes_fallback",
                    "created_at": datetime.now().isoformat(),
                    "focus_categories": focus_signals.get("top_failure_categories", []),
                },
            }
        )

    rng.shuffle(normalized)
    return normalized[:count]


def _select_core_scenarios(
    agent_slug: str,
    canonical: List[Dict[str, Any]],
    difficulty: str,
    core_count: int,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    canonical_copy = list(canonical)
    rng.shuffle(canonical_copy)

    if agent_slug.lower() != "amy" or str(difficulty).lower() not in {"cooperative", "mixed", "skeptical"}:
        return canonical_copy[:core_count] if canonical_copy else []

    preferred: List[Dict[str, Any]] = []
    stress: List[Dict[str, Any]] = []
    for scenario in canonical_copy:
        tags = [str(tag).lower() for tag in (scenario.get("tags") or [])]
        realism = str(scenario.get("realism_label") or "live_like").lower()
        scenario_difficulty = str(scenario.get("difficulty") or "medium").lower()
        if (
            "security" in tags
            or "proof_pressure" in tags
            or realism == "red_team"
            or scenario_difficulty == "hard"
        ):
            stress.append(scenario)
        else:
            preferred.append(scenario)

    selected = preferred[:core_count]
    if len(selected) < core_count:
        selected.extend(stress[: max(0, core_count - len(selected))])
    return selected[:core_count]


def build_batch_plan(
    agent_slug: str,
    scenario_pack: str,
    difficulty: str,
    count: int,
    seed: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    canonical = _get_pack_scenarios(scenario_pack)
    rng = random.Random(seed)

    adaptive_count = max(1, min(count // 2, 2)) if count >= 3 else 0
    core_count = max(count - adaptive_count, 1)
    selected_core = _select_core_scenarios(agent_slug, canonical, difficulty, core_count, seed=seed)
    adaptive = generate_adaptive_scenarios(
        agent_slug=agent_slug,
        pack_name=scenario_pack,
        count=adaptive_count,
        difficulty=difficulty,
        seed=seed,
    ) if adaptive_count else []

    planned: List[Dict[str, Any]] = []
    for scenario in selected_core:
        planned.append(
            {
                **scenario,
                "source": "canonical",
                "source_pack": scenario_pack,
                "pack_class": "core",
                "realism_label": scenario.get("realism_label") or "live_like",
                "lane": scenario.get("lane") or "core",
                "pressure_level": scenario.get("pressure_level") or "medium",
                "provenance": {
                    "generator": "canonical_library",
                    "created_at": datetime.now().isoformat(),
                },
            }
        )
    for scenario in adaptive:
        planned.append({**scenario, "pack_class": "adaptive"})

    rng.shuffle(planned)

    manifest_id = f"mel_manifest_{uuid.uuid4().hex[:8]}"
    source_counts = Counter(item.get("source", "unknown") for item in planned)
    pack_class_counts = Counter(item.get("pack_class", "unknown") for item in planned)
    manifest = {
        "manifest_id": manifest_id,
        "agent_slug": agent_slug,
        "created_at": datetime.now().isoformat(),
        "scenario_pack": scenario_pack,
        "difficulty": difficulty,
        "total_scenarios": len(planned),
        "source_counts": dict(source_counts),
        "pack_class_counts": dict(pack_class_counts),
        "focus_signals": _derive_focus_signals(agent_slug),
        "scenarios": [
            {
                "scenario_id": item.get("scenario_id"),
                "title": item.get("title"),
                "source": item.get("source"),
                "pack_class": item.get("pack_class"),
                "lane": item.get("lane"),
                "pressure_level": item.get("pressure_level"),
                "realism_label": item.get("realism_label"),
                "source_scenario_id": item.get("source_scenario_id"),
            }
            for item in planned
        ],
    }
    return planned[:count], manifest


def persist_batch_manifest(manifest: Dict[str, Any], batch_id: Optional[str] = None) -> str:
    manifests_dir = MEL_DIR / "batches"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    suffix = batch_id or manifest.get("manifest_id") or uuid.uuid4().hex[:8]
    path = manifests_dir / f"{suffix}_manifest.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return str(path)
