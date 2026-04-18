import json
from pathlib import Path


def test_record_lesson_dedupes_by_key(monkeypatch, tmp_path):
    from tools import hermes_memory

    monkeypatch.setattr(hermes_memory, "HERMES_DIR", tmp_path)
    monkeypatch.setattr(hermes_memory, "LESSONS_PATH", tmp_path / "lessons.jsonl")

    first = hermes_memory.record_lesson(
        source="mel",
        title="Test lesson",
        summary="A useful summary.",
        tags=["mel"],
        dedupe_key="lesson:test",
    )
    second = hermes_memory.record_lesson(
        source="mel",
        title="Test lesson updated",
        summary="A different summary that should be ignored.",
        tags=["mel"],
        dedupe_key="lesson:test",
    )

    assert first["_existing"] is False
    assert second["_existing"] is True
    assert second["summary"] == "A useful summary."


def test_backlog_miner_creates_lessons_and_report(monkeypatch, tmp_path):
    from tools import hermes_backlog_miner, hermes_memory

    pending_dir = tmp_path / "pending"
    batches_dir = tmp_path / "batches"
    reports_dir = tmp_path / "reports"
    hermes_dir = tmp_path / "hermes"
    pending_dir.mkdir()
    (batches_dir / "mel_batch_1").mkdir(parents=True)

    monkeypatch.setattr(hermes_backlog_miner, "PENDING_DIR", pending_dir)
    monkeypatch.setattr(hermes_backlog_miner, "BATCHES_DIR", batches_dir)
    monkeypatch.setattr(hermes_backlog_miner, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(hermes_memory, "HERMES_DIR", hermes_dir)
    monkeypatch.setattr(hermes_memory, "LESSONS_PATH", hermes_dir / "lessons.jsonl")

    pending_payload = {
        "pending_id": "amy_1",
        "agent_slug": "amy",
        "status": "rejected",
        "diagnostic": {"failure_category": "flow_naturalness"},
        "baseline": {"score": 70.2, "batch_id": "mel_batch_1"},
        "recommendation": {
            "variant": "strict",
            "score": 77.2,
            "improvement": 7.0,
            "result": {"batch_id": "mel_batch_1"},
        },
    }
    (pending_dir / "amy_1.json").write_text(json.dumps(pending_payload), encoding="utf-8")

    batch_payload = {
        "runs": [
            {
                "warnings": ["Repeated email request loop."],
                "categories": [
                    {
                        "key": "flow_naturalness",
                        "fail_flag": True,
                        "notes": "The agent repeated the same fallback structure.",
                    }
                ],
            }
        ]
    }
    (batches_dir / "mel_batch_1" / "batch_summary.json").write_text(json.dumps(batch_payload), encoding="utf-8")

    result = hermes_backlog_miner.mine_historical_mel_backlog()

    assert result["pending_files_scanned"] == 1
    assert result["agents_mined"] == ["amy"]
    assert Path(result["report_path"]).exists()

    lessons = hermes_memory.load_lessons(limit=-1)
    titles = [lesson["title"] for lesson in lessons]
    assert "amy backlog review amy_1" in titles
    assert "amy recurring MEL blocker" in titles
    assert "amy score-lift caution" in titles
