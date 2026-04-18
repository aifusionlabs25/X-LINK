import json


def test_select_relevant_skills_matches_telemetry_language():
    from tools.hermes_memory import select_relevant_skills

    skills = select_relevant_skills("Show me telemetry, token usage, and what the 5080 is doing.")
    slugs = [skill["slug"] for skill in skills]
    assert "telemetry_observatory" in slugs


def test_build_hermes_grounding_includes_lessons(monkeypatch, tmp_path):
    from tools import hermes_memory

    monkeypatch.setattr(hermes_memory, "HERMES_DIR", tmp_path)
    monkeypatch.setattr(hermes_memory, "LESSONS_PATH", tmp_path / "lessons.jsonl")

    hermes_memory.record_lesson(
        source="mel",
        title="Harness alignment matters",
        summary="Repeated brevity failures may indicate rubric mismatch, not just prompt weakness.",
        tags=["mel", "rubric"],
        confidence=0.82,
        evidence_paths=[str(hermes_memory.ROOT_DIR / "vault" / "mel" / "pending" / "amy_test.json")],
    )

    text = hermes_memory.build_hermes_grounding("We need help with MEL scoring and rubric drift.")
    assert "HERMES SKILLS" in text
    assert "HERMES LESSONS" in text
    assert "Harness alignment matters" in text


def test_record_lesson_filters_untrusted_session_logs(monkeypatch, tmp_path):
    from tools import hermes_memory

    monkeypatch.setattr(hermes_memory, "HERMES_DIR", tmp_path)
    monkeypatch.setattr(hermes_memory, "LESSONS_PATH", tmp_path / "lessons.jsonl")

    result = hermes_memory.record_lesson(
        source="mel",
        title="Noisy session trace",
        summary="Should not be ingested.",
        tags=["mel"],
        confidence=0.5,
        evidence_paths=[str(tmp_path / "vault" / "mel" / "logs" / "session_20260408.log")],
        dedupe_key="test:untrusted-log",
    )

    assert result["_skipped_untrusted"] is True
    assert not hermes_memory.LESSONS_PATH.exists()


def test_load_lessons_ignores_untrusted_rows(monkeypatch, tmp_path):
    from tools import hermes_memory

    lessons_path = tmp_path / "lessons.jsonl"
    monkeypatch.setattr(hermes_memory, "HERMES_DIR", tmp_path)
    monkeypatch.setattr(hermes_memory, "LESSONS_PATH", lessons_path)

    trusted_path = str(hermes_memory.ROOT_DIR / "vault" / "mel" / "pending" / "amy_1.json")
    lessons_path.write_text(
        json.dumps(
            {
                "source": "mel",
                "title": "trusted",
                "summary": "ok",
                "evidence_paths": [trusted_path],
            }
        )
        + "\n"
        + json.dumps(
            {
                "source": "mel",
                "title": "untrusted",
                "summary": "bad",
                "evidence_paths": [str(tmp_path / "vault" / "mel" / "logs" / "session_1.log")],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lessons = hermes_memory.load_lessons(limit=-1, trusted_only=True)
    assert [lesson["title"] for lesson in lessons] == ["trusted"]
