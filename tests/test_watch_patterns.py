import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


def test_default_watch_patterns_include_eval_and_archive_signals():
    from tools.watch_patterns import default_watch_patterns

    eval_patterns = default_watch_patterns("eval")
    archive_patterns = default_watch_patterns("archive")

    assert any(item["key"] == "run_active" for item in eval_patterns)
    assert any(item["key"] == "approval" for item in archive_patterns)


def test_append_watched_event_adds_matches_and_dedupes_identical_events():
    from tools.watch_patterns import append_watched_event, default_watch_patterns

    state = {
        "watch_patterns": default_watch_patterns("archive"),
        "events": [],
        "matched_signals": [],
    }

    state = append_watched_event(
        state,
        kind="archive",
        status="running",
        phase="folder_confirmation",
        detail="Waiting for Founder to confirm ChatGPT folder 'X Agents'.",
    )

    assert len(state["events"]) == 1
    assert any(signal["key"] == "approval" for signal in state["events"][0]["matched_signals"])
    assert state["latest_signal"]["key"] == "approval"

    state = append_watched_event(
        state,
        kind="archive",
        status="running",
        phase="folder_confirmation",
        detail="Waiting for Founder to confirm ChatGPT folder 'X Agents'.",
    )

    assert len(state["events"]) == 1


def test_append_watched_event_tracks_success_and_error_signals():
    from tools.watch_patterns import append_watched_event, default_watch_patterns

    state = {
        "watch_patterns": default_watch_patterns("eval"),
        "events": [],
        "matched_signals": [],
    }

    state = append_watched_event(
        state,
        kind="eval",
        status="running",
        phase="running",
        detail="Simulating Run 1",
        step="Simulating Run 1",
        percent=10,
    )
    state = append_watched_event(
        state,
        kind="eval",
        status="completed",
        phase="completed",
        detail="Batch completed. Verdict: NO_SHIP",
        percent=100,
    )

    keys = [signal["key"] for signal in state["matched_signals"]]
    assert "run_active" in keys
    assert "completed" in keys
