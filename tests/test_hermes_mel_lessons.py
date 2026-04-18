from pathlib import Path


def test_generate_challengers_includes_recent_lessons(monkeypatch):
    from tools import mel_pilot

    captured = {}

    class FakeRunner:
        def __init__(self, model):
            captured["model"] = model

        def run_reviewer(self, config_path, inputs):
            captured["config_path"] = config_path
            captured["inputs"] = inputs
            return {
                "patch_candidate": "Keep answers grounded.",
                "rationale": "Use lesson-informed revisions.",
                "risk_note": "",
                "thinking": "",
            }

    monkeypatch.setattr(mel_pilot, "ReviewerRunner", FakeRunner)
    monkeypatch.setattr(
        mel_pilot,
        "load_lessons",
        lambda limit=12: [
            {
                "title": "amy security loop",
                "summary": "Avoid repeating proof-boundary language under pressure.",
                "tags": ["mel", "amy"],
            },
            {
                "title": "ignore me",
                "summary": "Unrelated lesson.",
                "tags": ["telemetry"],
            },
        ],
    )

    challengers = mel_pilot.generate_challengers(
        {
            "slug": "dani",
            "name": "Dani",
            "persona": "Original persona text.",
        },
        {
            "failure_category": "flow_naturalness",
            "failure_rate": 66.7,
            "failed_exchange": "User asked for proof twice.",
            "baseline_score": 71.1,
            "baseline_pass_rate": 33.3,
        },
    )

    assert len(challengers) == 2
    review = captured["inputs"]["conversation_review"]
    assert "Relevant Hermes lessons" in review
    assert "amy security loop" in review
    assert "Unrelated lesson" not in review
    assert "HERMES PATCH BRIEF" in review


def test_record_mel_cycle_lesson_writes_pending_reference(monkeypatch, tmp_path):
    from tools import mel_pilot

    recorded = {}
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    monkeypatch.setattr(mel_pilot, "PENDING_DIR", str(pending_dir))

    def fake_record_lesson(**kwargs):
        recorded.update(kwargs)
        return kwargs

    monkeypatch.setattr(mel_pilot, "record_lesson", fake_record_lesson)

    snapshot_path = str(tmp_path / "amy_snapshot.md")
    mel_pilot._record_mel_cycle_lesson(
        agent_slug="amy",
        diagnostic={"failure_category": "flow_naturalness"},
        baseline_result={"score": 70.2},
        best_challenger={"score": 77.2},
        improvement=7.0,
        pending_id="amy_20260407_190444",
        snapshot_path=snapshot_path,
    )

    assert recorded["source"] == "mel"
    assert recorded["tags"] == ["mel", "amy", "flow_naturalness"]
    assert snapshot_path in recorded["evidence_paths"]
    assert str(Path(pending_dir) / "amy_20260407_190444.json") in recorded["evidence_paths"]


def test_generate_challengers_includes_hermes_patch_brief(monkeypatch):
    from tools import mel_pilot

    captured = {}

    class FakeRunner:
        def __init__(self, model):
            captured["model"] = model

        def run_reviewer(self, config_path, inputs):
            captured["inputs"] = inputs
            return {
                "patch_candidate": "Change structure.",
                "rationale": "Use the patch brief.",
                "risk_note": "",
                "thinking": "",
            }

    monkeypatch.setattr(mel_pilot, "ReviewerRunner", FakeRunner)
    monkeypatch.setattr(
        mel_pilot,
        "load_lessons",
        lambda limit=12: [
            {
                "title": "amy recurring MEL blocker",
                "summary": "Avoid repetitive fallback loops in proof-heavy security conversations.",
                "tags": ["mel", "amy", "flow_naturalness"],
            },
            {
                "title": "amy score-lift caution",
                "summary": "Score improvements alone are not enough.",
                "tags": ["mel", "amy", "false_positive_risk"],
            },
        ],
    )

    mel_pilot.generate_challengers(
        {"slug": "dani", "name": "Dani", "persona": "Original persona text."},
        {
            "failure_category": "flow_naturalness",
            "failure_rate": 66.7,
            "failed_exchange": "User kept pressing for proof.",
            "baseline_score": 71.1,
            "baseline_pass_rate": 0.0,
        },
    )

    review = captured["inputs"]["conversation_review"]
    assert "HERMES PATCH BRIEF" in review
    assert "Do not optimize for score lift alone" in review
    assert "Prioritize breaking repetitive fallback loops" in review


def test_checkpoint_restore_roundtrip(monkeypatch, tmp_path):
    from tools import mel_pilot

    agents_yaml = tmp_path / "agents.yaml"
    checkpoints_dir = tmp_path / "checkpoints"
    agents_yaml.write_text(
        "agents:\n"
        "- slug: amy\n"
        "  name: Amy\n"
        "  persona: Original Amy persona\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mel_pilot, "AGENTS_YAML", str(agents_yaml))
    monkeypatch.setattr(mel_pilot, "CHECKPOINTS_DIR", str(checkpoints_dir))
    monkeypatch.setattr(mel_pilot, "record_lesson", lambda **kwargs: kwargs)

    checkpoint = mel_pilot.create_persona_checkpoint("amy", label="pre-hermes-first", notes="Safety rollback.")
    assert checkpoint["agent_slug"] == "amy"

    agents_yaml.write_text(
        "agents:\n"
        "- slug: amy\n"
        "  name: Amy\n"
        "  persona: Changed Amy persona\n",
        encoding="utf-8",
    )

    restored = mel_pilot.restore_persona_checkpoint(checkpoint["checkpoint_id"])
    assert restored["status"] == "restored"
    contents = agents_yaml.read_text(encoding="utf-8")
    assert "Original Amy persona" in contents


def test_save_pending_recommends_baseline_when_challengers_regress(monkeypatch, tmp_path):
    import json
    from tools import mel_pilot

    monkeypatch.setattr(mel_pilot, "PENDING_DIR", str(tmp_path))

    pending_id = mel_pilot.save_pending(
        agent_slug="amy",
        diagnostic={"failure_category": "flow_naturalness"},
        baseline_result={"score": 70.5, "pass_rate": 0.0, "verdict": "NO_SHIP"},
        challengers=[
            {"variant": "lean", "prompt": "lean prompt", "patch": "lean patch", "rationale": "lean why", "risk_note": ""},
            {"variant": "strict", "prompt": "strict prompt", "patch": "strict patch", "rationale": "strict why", "risk_note": ""},
        ],
        challenger_results=[
            {"score": 60.6, "pass_rate": 0.0, "verdict": "NO_SHIP"},
            {"score": 65.4, "pass_rate": 0.0, "verdict": "NO_SHIP"},
        ],
        snapshot_path=str(tmp_path / "amy_snapshot.txt"),
    )

    payload = json.loads((tmp_path / f"{pending_id}.json").read_text(encoding="utf-8"))
    assert payload["recommendation"]["variant"] == "baseline"
    assert payload["recommendation"]["prompt"] == ""
    assert payload["recommendation"]["patch"] == ""
    assert payload["recommendation"]["passes_threshold"] is False


def test_extract_diagnostic_uses_batch_scores_and_failed_run_notes():
    from tools import mel_pilot

    batch = {
        "batch_id": "mel_test_batch",
        "average_score": 74.5,
        "pass_rate": 0.0,
        "category_averages": {
            "flow_naturalness": 2.2,
            "compliance_safety": 4.0,
        },
        "top_failure_categories": ["flow_naturalness"],
        "runs": [
            {
                "run_id": "mel_run_test",
                "pass_fail": "FAIL_BLOCK_RELEASE",
                "categories": [
                    {
                        "key": "flow_naturalness",
                        "label": "Flow and Naturalness",
                        "score": 2,
                        "notes": "Amy kept repeating the same templated handoff line.",
                        "fail_flag": True,
                    }
                ],
                "critical_failures": ["forbidden ownership wording: I'll ensure"],
                "warnings": [],
            }
        ],
    }

    diagnostic = mel_pilot.extract_diagnostic("amy", batch)
    assert diagnostic["baseline_score"] == 74.5
    assert diagnostic["baseline_pass_rate"] == 0.0
    assert diagnostic["failure_category"] == "flow_naturalness"
    assert "Flow and Naturalness" in diagnostic["failed_exchange"]
    assert "I'll ensure" in diagnostic["failed_exchange"]


def test_find_failed_snippet_falls_back_to_batch_summary():
    from tools import mel_pilot

    batch = {
        "average_score": 74.5,
        "pass_rate": 0.0,
        "category_averages": {
            "flow_naturalness": 2.2,
            "compliance_safety": 4.0,
        },
        "top_failure_categories": ["flow_naturalness"],
        "runs": [],
        "run_ids": [],
    }

    snippet = mel_pilot._find_failed_snippet("amy", batch)
    assert "Weakest category: flow_naturalness" in snippet
    assert "batch_average=74.5" in snippet
    assert "pass_rate=0.0" in snippet
