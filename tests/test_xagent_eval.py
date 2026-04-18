"""
X-Agent Eval v1 — Smoke Tests
Validates: router, scenario loading, scoring rubric, transcript normalization,
batch aggregation, review packet generation, and error handling.
"""

import os
import sys
import json
import pytest
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


# ── 1. Tool resolves through router ──────────────────────────

def test_eval_tool_resolves():
    from hub.router import resolve_tool
    tool = resolve_tool("xagent_eval")
    assert tool is not None
    assert tool.__class__.__name__ == "XAgentEvalTool"
    assert tool.key == "xagent_eval"


# ── 2. Scenario pack loads ────────────────────────────────────

def test_scenario_pack_loads():
    from tools.xagent_eval.scenario_bank import load_scenario_pack
    scenarios = load_scenario_pack("default_pack")
    assert len(scenarios) == 4
    assert all("scenario_id" in s for s in scenarios)
    assert all("title" in s for s in scenarios)
    assert all("opening_message" in s for s in scenarios)


def test_scenario_selection():
    from tools.xagent_eval.scenario_bank import select_scenarios
    selected = select_scenarios("default_pack", count=6, difficulty="mixed", seed=42)
    assert len(selected) == 6


def test_scenario_difficulty_filter():
    from tools.xagent_eval.scenario_bank import select_scenarios
    easy = select_scenarios("default_pack", count=3, difficulty="easy", seed=1)
    assert all(s.get("difficulty") == "easy" for s in easy)


def test_scenario_pack_list():
    from tools.xagent_eval.scenario_bank import list_packs
    packs = list_packs()
    assert "default_pack" in packs


# ── 3. Scoring rubric loads ──────────────────────────────────

def test_scoring_rubric_loads():
    from tools.xagent_eval.scoring import load_rubric
    rubric = load_rubric("default_v1")
    assert "categories" in rubric
    assert len(rubric["categories"]) == 9
    keys = [c["key"] for c in rubric["categories"]]
    assert "greeting_first_impression" in keys
    assert "compliance_safety" in keys
    assert "objection_handling" in keys


def test_scoring_rubric_weights():
    from tools.xagent_eval.scoring import load_rubric
    rubric = load_rubric("default_v1")
    total_weight = sum(c["weight"] for c in rubric["categories"])
    assert total_weight == 100


# ── 4. Transcript normalization ──────────────────────────────

def test_transcript_normalization():
    from tools.xagent_eval.transcript_normalizer import normalize_transcript
    raw = [
        {"turn": 1, "speaker": "test_user", "text": "Hello!"},
        {"turn": 2, "speaker": "agent_under_test", "text": "Hi there."},
        {"turn": 3, "speaker": "agent_under_test", "text": "How can I help?"},  # merge
        {"turn": 4, "speaker": "test_user", "text": "  [typing...]  "},  # cleaned
        {"turn": 5, "speaker": "test_user", "text": "Tell me about pricing."},
    ]
    normalized = normalize_transcript(raw)
    assert len(normalized) == 3  # merged same-speaker, cleaned empty
    assert normalized[0]["speaker"] == "test_user"
    assert normalized[1]["speaker"] == "agent_under_test"
    assert "How can I help?" in normalized[1]["text"]
    assert normalized[2]["speaker"] == "test_user"
    assert normalized[2]["turn"] == 3


def test_transcript_to_text():
    from tools.xagent_eval.transcript_normalizer import transcript_to_text
    turns = [
        {"turn": 1, "speaker": "test_user", "text": "Hello"},
        {"turn": 2, "speaker": "agent_under_test", "text": "Hi there"},
    ]
    text = transcript_to_text(turns)
    assert "[Turn 1] USER: Hello" in text
    assert "[Turn 2] AGENT: Hi there" in text


def test_transcript_stats():
    from tools.xagent_eval.transcript_normalizer import transcript_stats
    turns = [
        {"turn": 1, "speaker": "test_user", "text": "Hello world"},
        {"turn": 2, "speaker": "agent_under_test", "text": "Hi there, welcome."},
        {"turn": 3, "speaker": "test_user", "text": "Thanks"},
    ]
    stats = transcript_stats(turns)
    assert stats["total_turns"] == 3
    assert stats["user_turns"] == 2
    assert stats["agent_turns"] == 1


# ── 5. Batch summary aggregation ─────────────────────────────

def test_batch_aggregation():
    from tools.xagent_eval.schemas import EvalInputs, Scorecard, CategoryScore
    from tools.xagent_eval.batch_runner import aggregate_batch

    inputs = EvalInputs(target_agent="Morgan", scenario_pack="default_pack", runs=2)

    sc1 = Scorecard(run_id="r1", scenario_id="SC_COOP_001", target_agent="Morgan",
                    overall_score=85, pass_fail="PASS")
    sc1.categories = [CategoryScore(key="greeting_first_impression", label="Greeting", score=4, weight=10)]

    sc2 = Scorecard(run_id="r2", scenario_id="SC_SKEP_001", target_agent="Morgan",
                    overall_score=65, pass_fail="FAIL")
    sc2.categories = [CategoryScore(key="greeting_first_impression", label="Greeting", score=2, weight=10)]

    summary = aggregate_batch("batch_test", inputs, [sc1, sc2], ["r1", "r2"])
    assert summary.total_runs == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.pass_rate == 50.0
    assert summary.average_score == 75.0
    assert summary.category_averages["greeting_first_impression"] == 3.0


def test_batch_aggregation_counts_all_attempted_runs():
    from tools.xagent_eval.schemas import EvalInputs, Scorecard
    from tools.xagent_eval.batch_runner import aggregate_batch

    inputs = EvalInputs(target_agent="Morgan", scenario_pack="default_pack", runs=2)
    sc1 = Scorecard(run_id="r1", scenario_id="SC_COOP_001", target_agent="Morgan",
                    overall_score=85, pass_fail="PASS")

    summary = aggregate_batch("batch_test", inputs, [sc1], ["r1", "r2"])
    assert summary.total_runs == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.pass_rate == 50.0


def test_ollama_generate_text_returns_timeout_error(monkeypatch):
    from tools.xagent_eval import batch_runner

    def fake_post(*args, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(batch_runner.requests, "post", fake_post)

    text, error = batch_runner._ollama_generate_text("fake-model", "hello")
    assert text is None
    assert error == "ollama_timeout:fake-model"


def test_compile_eval_persona_compacts_large_amy_prompt():
    from tools.xagent_eval import batch_runner

    long_persona = "You are Amy.\n" + ("Rule line.\n" * 900)
    compact = batch_runner._compile_eval_persona("amy", long_persona, "IT Services")

    assert len(compact) < 2500
    assert "Do not invent exact operating details" in compact
    assert "Do not ask the same discovery question twice" in compact
    assert "You are Amy, a senior SDR-style representative" in compact


def test_build_agent_context_window_caps_history(monkeypatch):
    from tools.xagent_eval import batch_runner

    monkeypatch.setattr(batch_runner, "MEL_AGENT_CONTEXT_LINES", 4)
    monkeypatch.setattr(batch_runner, "MEL_AGENT_CONTEXT_CHARS", 220)
    conversation = [f"User: message {idx} " + ("x" * 80) for idx in range(8)]

    window = batch_runner._build_agent_context_window(conversation)

    assert "[Earlier exchanges omitted:" in window
    assert "message 0" not in window
    assert "message 7" in window
    assert len(window) <= 260


def test_amy_recent_proof_pressure_count_detects_repeated_pressure():
    from tools.xagent_eval import batch_runner

    conversation = [
        "User: Can you show me documentation for the monitoring?",
        "Amy: I can stay high level here.",
        "User: Do you have a case study or proof?",
    ]

    count = batch_runner._amy_recent_proof_pressure_count(
        "AMY_SECURITY_STANCE",
        conversation,
        "What exact real-time monitoring do you provide?",
    )

    assert count == 3


def test_amy_safe_reframe_does_not_use_handoff_close_for_unaccepted_proof_loop():
    from tools.xagent_eval import batch_runner

    reply = batch_runner._amy_safe_reframe(
        "I appreciate the overview, but what specific tools or technologies do you use?",
        "AMY_SECURITY_STANCE",
        True,
        "loop",
        [
            "User: Our security posture is under constant threat.",
            "Amy: I cannot verify exact response times or operating mechanics in chat.",
        ],
    )

    assert reply != "That works. Thanks."
    assert "verify" in reply.lower() or "proof packet" in reply.lower() or "overstate" in reply.lower()


def test_build_failure_scorecard_preserves_runtime_failures():
    from tools.xagent_eval.batch_runner import build_failure_scorecard
    from tools.xagent_eval.schemas import RunMetadata

    metadata = RunMetadata(
        run_id="run_timeout",
        batch_id="batch_timeout",
        target_agent="amy",
        environment="sim",
        scenario_pack="amy_it_discovery",
        scenario_id="AMY_CIO_TRANSFORM",
        scenario_title="CIO",
        difficulty="mixed",
        max_turns=8,
        status="error",
        error_message="ollama_timeout:qwen2.5:14b-instruct-q6_K",
        completion_reason="agent_generation_failed",
    )

    scorecard = build_failure_scorecard(metadata, [{"turn": 1, "speaker": "test_user", "text": "hello"}])

    assert scorecard.pass_fail == "FAIL_BLOCK_RELEASE"
    assert scorecard.classification == "review_runtime_failure"
    assert scorecard.categories[0].key == "runtime_reliability"
    assert "timeout" in scorecard.critical_failures[0]


def test_batch_aggregation_counts_runtime_failures():
    from tools.xagent_eval.batch_runner import aggregate_batch, build_failure_scorecard
    from tools.xagent_eval.schemas import EvalInputs, RunMetadata

    inputs = EvalInputs(target_agent="amy", scenario_pack="amy_it_discovery", runs=1)
    metadata = RunMetadata(
        run_id="run_timeout",
        batch_id="batch_timeout",
        target_agent="amy",
        environment="sim",
        scenario_pack="amy_it_discovery",
        scenario_id="AMY_CIO_TRANSFORM",
        scenario_title="CIO",
        difficulty="mixed",
        max_turns=8,
        status="error",
        error_message="ollama_timeout:qwen2.5:14b-instruct-q6_K",
        completion_reason="agent_generation_failed",
    )

    scorecard = build_failure_scorecard(metadata, [])
    summary = aggregate_batch("batch_timeout", inputs, [scorecard], ["run_timeout"])

    assert summary.verdict == "NO_SHIP"
    assert summary.failed == 1
    assert summary.data["runtime_failure_count"] == 1
    assert summary.runs[0]["classification"] == "review_runtime_failure"


def test_user_simulator_retries_with_fallback_model(monkeypatch):
    from tools.xagent_eval import batch_runner

    calls = []

    def fake_generate(model, prompt, **kwargs):
        calls.append(model)
        if len(calls) == 1:
            return None, f"ollama_request_error:{model}:404 Client Error"
        return "Prospect reply", None

    monkeypatch.setattr(batch_runner, "_ollama_generate_text", fake_generate)
    monkeypatch.setattr(batch_runner, "SIM_USER_FALLBACK_MODELS", ["llama3.2:latest"])

    text, error = batch_runner._generate_user_sim_text("hello", preferred_model="missing-model", fallback_model="working-model")
    assert text == "Prospect reply"
    assert error is None
    assert calls == ["missing-model", "llama3.2:latest"]


def test_user_simulator_uses_small_model_first_by_default(monkeypatch):
    from tools.xagent_eval import batch_runner

    calls = []

    def fake_generate(model, prompt, **kwargs):
        calls.append((model, kwargs.get("options", {}).get("num_predict")))
        return "Prospect reply", None

    monkeypatch.setattr(batch_runner, "_ollama_generate_text", fake_generate)
    monkeypatch.setattr(batch_runner, "SIM_USER_FALLBACK_MODELS", ["llama3.2:latest", "qwen2.5:14b-instruct-q6_K"])
    monkeypatch.setattr(batch_runner, "OLLAMA_SIM_NUM_PREDICT", 48)

    text, error = batch_runner._generate_user_sim_text("hello", preferred_model=None, fallback_model="qwen2.5:14b-instruct-q6_K")

    assert text == "Prospect reply"
    assert error is None
    assert calls == [("llama3.2:latest", 48)]


def test_build_sim_user_rules_adds_human_realism():
    from tools.xagent_eval import batch_runner

    scenario = {
        "human_profile": {
            "baseline_tone": "skeptical but reasonable",
            "softening_signals": ["If the agent gives one clear limit, soften on the next turn."],
            "unrealistic_request_handling": ["Do not demand the same impossible proof forever."],
        }
    }

    rules = batch_runner._build_sim_user_rules(
        scenario,
        agent_domain="IT Services",
        close_mode=True,
        slot_intercepted=False,
    )

    assert "real human buyer" in rules
    assert "skeptical but reasonable" in rules
    assert "do not keep demanding the exact same impossible proof forever" in rules
    assert "The conversation is near a natural stopping point" in rules
    assert "Real people sometimes accept a partial answer" in rules
    assert "acknowledge, accept, decline, or disengage briefly" in rules


def test_sanitize_agent_reply_strips_prompt_leakage_and_non_latin_content():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_CIO_TRANSFORM_001"}
    reply = (
        "### [Core Identity]\n"
        "You are Amy.\n"
        "这是内部分析。\n"
        "At a high level, yes. At a high level, yes.\n"
        "At a high level, yes."
    )

    cleaned = batch_runner._sanitize_agent_reply("amy", scenario, "Can you support migration?", reply, False)

    assert "### [" not in cleaned
    assert "这是内部分析" not in cleaned
    assert cleaned.count("At a high level") <= 1


def test_sanitize_agent_reply_reframes_ownership_language_for_amy():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_MONITOR_001"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "Can you send that over and book time?",
        "I'll get that request moving and I'll ensure the right team sends it over.",
        True,
    )

    lowered = cleaned.lower()
    assert "i'll" not in lowered
    assert "ensure" not in lowered
    assert "best email" in lowered or "verify" in lowered or "next step" in lowered


def test_sanitize_agent_reply_reframes_unverified_security_specifics_for_amy():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_MONITOR_001"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "How do you handle real-time monitoring?",
        "We use advanced detection mechanisms, continuous monitoring, configuration assistance, and toolkits for integration. Typical setup is a few weeks to a couple of months.",
        False,
    )

    lowered = cleaned.lower()
    assert "advanced detection mechanisms" not in lowered
    assert "continuous monitoring" not in lowered
    assert "few weeks to a couple of months" not in lowered
    assert "verify" in lowered or "monitoring model" in lowered or "timing or tooling" in lowered


def test_sanitize_agent_reply_varies_handoff_close_after_acceptance():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_MONITOR_001"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "Sounds good, looking forward to the call next week. Thanks.",
        "Understood. The next step would be a clean handoff so the right team can confirm details.",
        True,
    )

    assert cleaned in {
        "Thanks. We can leave it there.",
        "Sounds good. Thanks for the time.",
        "Appreciate it. Talk soon.",
    }


def test_sanitize_agent_reply_reframes_direct_to_me_and_confirmation_promises():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_MONITOR_001"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "Here is my contact info. Can you send a confirmation email once things are in motion?",
        "You can send the overview directly to me, and a confirmation email will be sent once the process is set in motion.",
        True,
    )

    lowered = cleaned.lower()
    assert "directly to me" not in lowered
    assert "confirmation email" not in lowered
    assert "best email" in lowered or "next step" in lowered or "leave it there" in lowered


def test_sanitize_agent_reply_breaks_understood_captured_team_loop():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_PROOF_PATH"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "No more back-and-forth until the case studies are in my inbox.",
        "Understood, Marcus. Your request is captured and the right team will follow up directly.",
        True,
    )

    assert cleaned in {
        "Understood. We can leave it there.",
        "That works. We can leave it there.",
        "Appreciate it. We can leave it there.",
    }


def test_sanitize_agent_reply_avoids_repeating_same_security_boundary():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_PROOF_PATH"}
    conversation = [
        "User: Before I take a call, I want proof.",
        "Amy: I can confirm the service area, but not the exact operating detail in chat.",
    ]

    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "Do not keep repeating yourself. If you have something real, say it now.",
        "I can confirm the service area, but not the exact operating detail in chat.",
        False,
        conversation,
    )

    assert cleaned != "I can confirm the service area, but not the exact operating detail in chat."
    assert "exact operating detail in chat" not in cleaned.lower()


def test_sanitize_agent_reply_strips_unverified_security_timing_claims():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_MONITOR_001"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "Can you give me a rough response-time estimate?",
        "At a high level, we typically respond within 1-5 minutes after detection and block the IP address automatically.",
        False,
    )

    lowered = cleaned.lower()
    assert "1-5 minutes" not in lowered
    assert "within 1-5 minutes" not in lowered
    assert "block the ip address" not in lowered
    assert "verify" in lowered or "timing" in lowered or "tooling" in lowered


def test_sanitize_agent_reply_strips_soft_security_ops_claims():
    from tools.xagent_eval import batch_runner

    scenario = {"scenario_id": "SC_AMY_SECURITY_MONITOR_001"}
    cleaned = batch_runner._sanitize_agent_reply(
        "amy",
        scenario,
        "Can you outline who handles the response process?",
        "The escalation process typically involves our security operations team, incident management, and external specialists depending on severity.",
        False,
    )

    lowered = cleaned.lower()
    assert "security operations team" not in lowered
    assert "incident management" not in lowered
    assert "external specialists" not in lowered
    assert "verify" in lowered or "monitoring model" in lowered or "service area" in lowered


def test_amy_terminal_close_detection_and_acceptance_helpers():
    from tools.xagent_eval import batch_runner

    assert batch_runner._amy_user_accepted_next_step("That works. Let's do Tuesday at 10 AM.")
    assert batch_runner._amy_is_terminal_close("Sounds good. We can leave it there.")
    assert batch_runner._amy_is_proof_pressure("AMY_SECURITY_PROOF_PATH", "Can you share proof or documentation?")


def test_score_run_emits_category_callbacks(monkeypatch):
    from tools.xagent_eval import scoring
    from tools.xagent_eval.schemas import CategoryScore

    monkeypatch.setattr(
        scoring,
        "load_rubric",
        lambda rubric_name="default_v1": {
            "categories": [
                {"key": "greeting_first_impression", "label": "Greeting", "weight": 10, "criteria": []},
                {"key": "flow_naturalness", "label": "Flow", "weight": 10, "criteria": []},
            ]
        },
    )
    monkeypatch.setattr(
        scoring,
        "score_category",
        lambda transcript, scenario, category, contract=None, rubric_name="default_v1": CategoryScore(
            key=category["key"],
            label=category["label"],
            score=4,
            weight=category["weight"],
            notes="ok",
            fail_flag=False,
        ),
    )

    started = []
    finished = []
    scorecard = scoring.score_run(
        run_id="r1",
        target_agent="Morgan",
        transcript=[{"speaker": "test_user", "text": "hi"}, {"speaker": "agent_under_test", "text": "hello"}],
        scenario={"scenario_id": "s1"},
        on_category_start=lambda idx, total, cat: started.append((idx, total, cat["key"])),
        on_category_scored=lambda idx, total, cat, cat_score: finished.append((idx, total, cat["key"], cat_score.score)),
    )

    assert scorecard.overall_score > 0
    assert started == [(1, 2, "greeting_first_impression"), (2, 2, "flow_naturalness")]
    assert finished == [(1, 2, "greeting_first_impression", 4), (2, 2, "flow_naturalness", 4)]


def test_consultative_sales_prompt_rewards_boundary_setting():
    from tools.xagent_eval import scoring

    prompt = scoring.build_scoring_prompt(
        transcript=[{"speaker": "agent_under_test", "text": "I cannot verify that in chat."}],
        scenario={"title": "Security Proof", "role": "security_director", "difficulty": "hard"},
        category={"key": "flow_naturalness", "label": "Flow", "criteria": []},
        rubric_name="consultative_sales_v1",
    )

    assert "Reward healthy human boundary-setting" in prompt
    assert "one truthful limit, one valid next step" in prompt
    assert "Reward clean human endings" in prompt


def test_amy_frontdoor_rubric_scores_as_sdr_not_security_architect():
    from tools.xagent_eval import scoring

    prompt = scoring.build_scoring_prompt(
        transcript=[{"speaker": "agent_under_test", "text": "At a high level, we can help there, and the right specialist can go deeper on the security detail."}],
        scenario={"title": "Security Stakeholder", "role": "security_manager", "difficulty": "medium"},
        category={"key": "role_fidelity", "label": "Role Fidelity", "criteria": []},
        rubric_name="amy_frontdoor_sdr_v1",
    )

    assert "frontline SDR" in prompt
    assert "Do NOT punish Amy merely for refusing to go deep" in prompt


def test_deterministic_scoring_skips_ollama_for_brevity(monkeypatch):
    from tools.xagent_eval import scoring

    def should_not_call(*args, **kwargs):
        raise AssertionError("LLM scorer should not be called for deterministic categories")

    monkeypatch.setattr(scoring, "_call_ollama_json", should_not_call)
    category = {"key": "brevity_efficiency", "label": "Brevity", "weight": 20}
    transcript = [
        {"speaker": "agent_under_test", "text": "Short answer."},
        {"speaker": "agent_under_test", "text": "Another short answer."},
    ]

    result = scoring.score_category(transcript, {"opening_message": "Hi"}, category)
    assert result.score == 5
    assert "1 to 2 sentence target" in result.notes


def test_hybrid_scoring_routes_fast_and_deep_models(monkeypatch):
    from tools.xagent_eval import scoring

    seen = []

    def fake_call(prompt, model, timeout):
        seen.append((model, timeout))
        return {"score": 4, "notes": "ok", "fail_flag": False}

    monkeypatch.setattr(scoring, "_call_ollama_json", fake_call)
    transcript = [{"speaker": "agent_under_test", "text": "Hello there."}]
    scenario = {"opening_message": "Hi"}

    fast = scoring.score_category(transcript, scenario, {"key": "accuracy_groundedness", "label": "Accuracy", "weight": 10})
    deep = scoring.score_category(transcript, scenario, {"key": "flow_naturalness", "label": "Flow", "weight": 10})

    assert fast.score == 4
    assert deep.score == 4
    assert seen[0][0] == scoring.FAST_MODEL
    assert seen[1][0] == scoring.DEEP_MODEL


def test_compliance_safety_does_not_flag_chatbot_or_curly_apostrophe():
    from tools.xagent_eval import scoring

    category = {"key": "compliance_safety", "label": "Compliance", "weight": 5}
    transcript = [
        {
            "speaker": "agent_under_test",
            "text": "X Agents feel more natural than text-based chatbots, and the user's setup determines the details.",
        }
    ]
    result = scoring.score_category(transcript, {"opening_message": "Hi"}, category)
    assert result.score == 5
    assert result.fail_flag is False


def test_compliance_safety_flags_non_latin_script_only():
    from tools.xagent_eval import scoring

    category = {"key": "compliance_safety", "label": "Compliance", "weight": 5}
    transcript = [
        {
            "speaker": "agent_under_test",
            "text": "Pricing depends on your needs. 具体的定价细节需要进一步确认。",
        }
    ]
    result = scoring.score_category(transcript, {"opening_message": "Hi"}, category)
    assert result.score == 1
    assert "non_latin_output" in result.notes


def test_score_run_marks_harness_autoscore_as_artifact(monkeypatch):
    from tools.xagent_eval import scoring
    from tools.xagent_eval.schemas import CategoryScore

    monkeypatch.setattr(
        scoring,
        "load_rubric",
        lambda rubric_name="default_v1": {
            "categories": [
                {"key": "flow_naturalness", "label": "Flow", "weight": 10, "criteria": []},
            ]
        },
    )
    monkeypatch.setattr(
        scoring,
        "score_category",
        lambda transcript, scenario, category, contract=None, rubric_name="default_v1": CategoryScore(
            key=category["key"],
            label=category["label"],
            score=3,
            weight=category["weight"],
            notes="Harness auto-score due to scoring error: timeout",
            fail_flag=False,
        ),
    )

    scorecard = scoring.score_run(
        run_id="r1",
        target_agent="Morgan",
        transcript=[{"speaker": "agent_under_test", "text": "Hello."}],
        scenario={"scenario_id": "s1"},
    )
    assert scorecard.harness_artifacts
    assert "Harness auto-score" in scorecard.harness_artifacts[0]


def test_reviewer_runner_fallback_patch_response():
    from tools.xagent_eval.reviewer_runner import ReviewerRunner

    runner = ReviewerRunner()
    result = runner._fallback_patch_response(reason="empty output")
    assert "patch_candidate" in result
    assert "Fallback heuristic patch" in result["rationale"]


def test_reviewer_runner_uses_configured_model_and_strict_json(tmp_path, monkeypatch):
    import json as _json
    from tools.xagent_eval.reviewer_runner import ReviewerRunner

    config_path = tmp_path / "troy.yaml"
    config_path.write_text(
        "\n".join([
            'name: troy',
            'model: "qwen2.5:14b-instruct-q6_K"',
            'strict_json: true',
            'expected_keys:',
            '  - patch_candidate',
            '  - rationale',
            '  - risk_note',
            '  - regression_scenarios',
            'system_prompt: |',
            '  hello {{ agent_name }}',
        ]),
        encoding="utf-8",
    )

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": _json.dumps({
                    "patch_candidate": "- Keep it short.",
                    "rationale": "Fix brevity.",
                    "risk_note": "Could be terse.",
                    "regression_scenarios": ["DANI_USE_CASE_DIVE"],
                })
            }

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr("tools.xagent_eval.reviewer_runner.requests.post", fake_post)

    runner = ReviewerRunner()
    result = runner.run_reviewer(str(config_path), {"agent_name": "Dani"})
    assert result["patch_candidate"] == "- Keep it short."
    assert captured["payload"]["model"] == "qwen2.5:14b-instruct-q6_K"
    assert captured["payload"]["format"] == "json"


def test_strip_existing_mel_patches_removes_old_tail():
    from tools.mel_pilot import _strip_existing_mel_patches

    original = "Base prompt.\n\n### [MEL PATCH — LEAN]\nold patch\n\n### [REINFORCED CONSTRAINTS]\n- rule"
    stripped = _strip_existing_mel_patches(original)
    assert stripped == "Base prompt."


def test_generate_challengers_uses_amy_manual_patch_for_flow_naturalness():
    from tools import mel_pilot

    challengers = mel_pilot.generate_challengers(
        {
            "slug": "amy",
            "name": "Amy",
            "persona": "Base Amy prompt.",
        },
        {
            "failure_category": "flow_naturalness",
            "failure_rate": 70.0,
            "baseline_score": 68.6,
            "baseline_pass_rate": 0.0,
            "failed_exchange": "loop",
        },
    )

    assert len(challengers) == 2
    assert challengers[0]["variant"] == "graceful_boundary_mode"
    assert challengers[1]["variant"] == "frontdoor_progression_mode"
    assert "one truthful high-level boundary" in challengers[0]["patch"]
    assert "Most realistic Amy conversations are broad enterprise discovery" in challengers[1]["patch"]
    assert all("Hermes manual Amy patch" in c["rationale"] for c in challengers)


def test_scoring_timeouts_increased_for_noisy_eval_runs():
    from tools.xagent_eval import scoring

    assert scoring.FAST_TIMEOUT == (5, 60)
    assert scoring.DEEP_TIMEOUT == (5, 180)


def test_summarize_progress_reports_warning_for_stale_scoring():
    from datetime import datetime, timedelta
    from tools.mel_pilot import summarize_progress

    progress = {
        "running": True,
        "agent": "dani",
        "last_pct": 68,
        "events": [
            {
                "stage": "baseline",
                "status": "active",
                "detail": "Scenario 1: Scoring 2/9",
                "timestamp": (datetime.now() - timedelta(seconds=61)).isoformat(),
                "data": {"phase": "scoring", "category_index": 2, "category_total": 9},
            }
        ],
    }

    enriched = summarize_progress(progress)
    assert enriched["summary"]["state"] == "warning"
    assert enriched["summary"]["current_stage"] == "baseline"
    assert "still scoring" in enriched["summary"]["warnings"][0]


def test_summarize_progress_collects_latest_error():
    from datetime import datetime
    from tools.mel_pilot import summarize_progress

    progress = {
        "running": False,
        "agent": "dani",
        "last_pct": 42,
        "events": [
            {
                "stage": "baseline",
                "status": "error",
                "detail": "Scenario 2: Scoring error",
                "timestamp": datetime.now().isoformat(),
                "data": {"phase": "scoring_error", "error": "timeout"},
            }
        ],
    }

    enriched = summarize_progress(progress)
    assert enriched["summary"]["state"] == "error"
    assert enriched["summary"]["latest_error"] == "Scenario 2: Scoring error"


def test_eval_contract_infers_speak_first_from_persona():
    import asyncio
    from tools.xagent_eval.tool import XAgentEvalTool

    tool = XAgentEvalTool()
    prepared = asyncio.run(tool.prepare(
        {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")},
        {"target_agent": "dani", "scenario_pack": "dani_platform_sales", "runs": 1},
    ))
    assert prepared is True
    assert tool.contract.conversation_start_mode == "speak_first"


def test_execute_simulated_run_supports_speak_first_contract(monkeypatch):
    import asyncio
    from tools.xagent_eval import batch_runner
    from tools.xagent_eval.schemas import EvalContract, EvalInputs, Scorecard

    def fake_generate(model, prompt, options=None, read_timeout=None, **kwargs):
        if "OPENING MODE" in prompt:
            return "I am Danny from AI Fusion Labs. Welcome in.", None
        if "RULES:" in prompt:
            return "Thanks.", None
        return "X Agents can guide virtual tours when configured.", None

    monkeypatch.setattr(batch_runner, "_ollama_generate_text", fake_generate)
    monkeypatch.setattr(
        batch_runner,
        "score_run",
        lambda **kwargs: Scorecard(
            run_id=kwargs["run_id"],
            scenario_id=kwargs["scenario"]["scenario_id"],
            target_agent=kwargs["target_agent"],
            overall_score=80,
            pass_fail="PASS",
        ),
    )

    inputs = EvalInputs(target_agent="dani", scenario_pack="dani_platform_sales", max_turns=1, pass_threshold=70)
    scenario = {
        "scenario_id": "DANI_USE_CASE_DIVE",
        "title": "Use case",
        "opening_message": "Can X Agents lead a virtual tour?",
        "difficulty": "medium",
        "user_profile": {"name": "Alex", "context": "Prospect"},
    }
    contract = EvalContract(conversation_start_mode="speak_first")
    metadata, transcript, scorecard = asyncio.run(
        batch_runner.execute_simulated_run("run1", "batch1", inputs, scenario, contract=contract)
    )

    assert metadata.status == "success"
    assert transcript[0]["speaker"] == "agent_under_test"
    assert transcript[1]["speaker"] == "test_user"
    assert scorecard.pass_fail == "PASS"


def test_execute_simulated_run_keeps_amy_agent_prompt_compact(monkeypatch):
    import asyncio
    from tools.xagent_eval import batch_runner
    from tools.xagent_eval.schemas import EvalInputs, Scorecard

    agent_prompts = []

    def fake_generate(model, prompt, options=None, read_timeout=None, **kwargs):
        if "RULES:" in prompt:
            return "Can you tell me a bit more about your environment?", None
        agent_prompts.append(prompt)
        return "I can stay high level here without guessing.", None

    monkeypatch.setattr(batch_runner, "_ollama_generate_text", fake_generate)
    monkeypatch.setattr(
        batch_runner,
        "score_run",
        lambda **kwargs: Scorecard(
            run_id=kwargs["run_id"],
            scenario_id=kwargs["scenario"]["scenario_id"],
            target_agent=kwargs["target_agent"],
            overall_score=80,
            pass_fail="PASS",
        ),
    )

    inputs = EvalInputs(target_agent="amy", scenario_pack="amy_it_discovery", max_turns=2, pass_threshold=70)
    scenario = {
        "scenario_id": "AMY_SECURITY_STANCE",
        "title": "Security stance",
        "opening_message": "How does Insight handle real-time security monitoring?",
        "difficulty": "medium",
        "context": "Prospect wants verified security information.",
        "goal": "Understand support and monitoring without overclaiming.",
        "user_profile": {"name": "Alex", "context": "Prospect"},
    }

    metadata, transcript, scorecard = asyncio.run(
        batch_runner.execute_simulated_run("run_compact", "batch_compact", inputs, scenario)
    )

    assert metadata.status == "success"
    assert scorecard.pass_fail == "PASS"
    assert agent_prompts
    assert max(len(prompt) for prompt in agent_prompts) < 6000
    if len(agent_prompts) >= 2:
        assert len(agent_prompts[1]) - len(agent_prompts[0]) < 800


def test_execute_simulated_run_forces_amy_terminal_close_on_repeated_proof_pressure(monkeypatch):
    import asyncio
    from tools.xagent_eval import batch_runner
    from tools.xagent_eval.schemas import EvalInputs, Scorecard

    agent_prompts = []
    user_turns = iter([
        "Can you show me a case study or proof?",
        "I still need exact real-time monitoring details.",
    ])

    def fake_generate(model, prompt, options=None, read_timeout=None, **kwargs):
        if "RULES:" in prompt:
            return next(user_turns, "Thanks, that helps."), None
        agent_prompts.append(prompt)
        return "We use advanced analytics and machine learning for true real-time monitoring.", None

    monkeypatch.setattr(batch_runner, "_ollama_generate_text", fake_generate)
    monkeypatch.setattr(
        batch_runner,
        "score_run",
        lambda **kwargs: Scorecard(
            run_id=kwargs["run_id"],
            scenario_id=kwargs["scenario"]["scenario_id"],
            target_agent=kwargs["target_agent"],
            overall_score=80,
            pass_fail="PASS",
        ),
    )

    inputs = EvalInputs(target_agent="amy", scenario_pack="amy_it_discovery", max_turns=3, pass_threshold=70)
    scenario = {
        "scenario_id": "AMY_SECURITY_STANCE",
        "title": "Security stance",
        "opening_message": "How does Insight handle security monitoring?",
        "difficulty": "medium",
        "context": "Prospect wants verified security information.",
        "goal": "Understand support and monitoring without overclaiming.",
        "user_profile": {"name": "Alex", "context": "Prospect"},
    }

    metadata, transcript, scorecard = asyncio.run(
        batch_runner.execute_simulated_run("run_proof_close", "batch_proof_close", inputs, scenario)
    )

    assert metadata.status == "success"
    assert scorecard.pass_fail == "PASS"
    assert metadata.close_reason == "proof_pressure_loop"
    agent_turns = [turn["text"] for turn in transcript if turn["speaker"] == "agent_under_test"]
    assert any("I cannot verify" in turn or "I do not have a verified proof packet" in turn for turn in agent_turns)
    assert all("advanced analytics" not in turn.lower() for turn in agent_turns)


# ── 6. Review packet generates ───────────────────────────────

def test_review_packet_generates():
    from tools.xagent_eval.schemas import BatchSummary, Scorecard
    from tools.xagent_eval.review_packet import generate_review_packet

    summary = BatchSummary(
        batch_id="test_batch", target_agent="Morgan",
        environment="prod", scenario_pack="default_pack",
        total_runs=3, passed=2, failed=1, pass_rate=66.7,
        average_score=72.5,
        category_averages={"greeting_first_impression": 4.0, "objection_handling": 2.5},
        top_failure_categories=["objection_handling"],
    )
    sc = Scorecard(run_id="r1", scenario_id="SC_SKEP_001", target_agent="Morgan",
                   overall_score=60, pass_fail="FAIL",
                   warnings=["Objection Handling: Failed to address pushback"])

    packet = generate_review_packet(summary, [sc], [{"scenario_id": "SC_SKEP_001", "title": "Skeptical"}])
    assert "REVIEW PACKET" in packet
    assert "Morgan" in packet
    assert "objection_handling" in packet
    assert "SUGGESTED PERSONA CHANGES" in packet


# ── 7. Invalid agent returns structured error ────────────────

def test_invalid_agent_error():
    import asyncio
    from tools.xagent_eval.tool import XAgentEvalTool
    tool = XAgentEvalTool()
    result = asyncio.run(tool.run(
        {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")},
        {"target_agent": ""}
    ))
    assert result.status == "error"
    assert "E_AGENT_NOT_FOUND" in str(result.data)


# ── 8. Invalid scenario pack returns structured error ────────

def test_invalid_scenario_pack_error():
    import asyncio
    from tools.xagent_eval.tool import XAgentEvalTool
    tool = XAgentEvalTool()
    result = asyncio.run(tool.run(
        {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")},
        {"target_agent": "Morgan", "scenario_pack": "nonexistent_pack"}
    ))
    assert result.status == "error"
    payload = str(result.data)
    assert "E_SCENARIO_LOAD_FAILED" in payload or "scenario_mismatch" in payload


def test_agent_lookup_accepts_display_name_case_insensitively():
    import asyncio
    from tools.xagent_eval.tool import XAgentEvalTool
    tool = XAgentEvalTool()
    result = asyncio.run(tool.run(
        {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")},
        {"target_agent": "Morgan", "scenario_pack": "default_pack", "runs": 0}
    ))
    assert "E_AGENT_NOT_FOUND" not in str(result.data)


# ── 9. Schemas validate ──────────────────────────────────────

def test_eval_inputs_from_dict():
    from tools.xagent_eval.schemas import EvalInputs
    inputs = EvalInputs.from_dict({
        "target_agent": "Morgan",
        "runs": 5,
        "difficulty": "hard",
    })
    assert inputs.target_agent == "Morgan"
    assert inputs.runs == 5
    assert inputs.difficulty == "hard"
    assert inputs.environment == "prod"
    assert inputs.max_turns == 12


def test_scorecard_serialization():
    from tools.xagent_eval.schemas import Scorecard, CategoryScore
    sc = Scorecard(run_id="r1", scenario_id="sc1", target_agent="Morgan",
                   overall_score=82, pass_fail="PASS")
    sc.categories = [CategoryScore(key="k", label="L", score=4, weight=10)]
    d = sc.to_dict()
    assert isinstance(d, dict)
    json.dumps(d)  # Must be serializable
