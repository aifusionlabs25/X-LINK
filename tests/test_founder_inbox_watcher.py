import json


def test_build_email_fingerprint_is_stable():
    from tools.founder_inbox_watcher import build_email_fingerprint

    one = build_email_fingerprint("aifusionlabs@gmail.com", "Subject", "Preview", "Body")
    two = build_email_fingerprint("aifusionlabs@gmail.com", "Subject", "Preview", "Body")
    assert one == two


def test_execute_founder_email_action_uses_bridge_reply_and_dispatch(monkeypatch):
    from tools import founder_inbox_watcher

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"reply": "Handled. I have it."}

    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return FakeResponse()

    def fake_dispatch(body, sender="aifusionlabs@gmail.com"):
        sent["dispatch_body"] = body
        sent["dispatch_sender"] = sender
        return {"success": True, "stdout": "Reply sent to aifusionlabs@gmail.com successfully."}

    result = founder_inbox_watcher.execute_founder_email_action(
        "Subject line",
        "Email body",
        chat_post=fake_post,
        reply_dispatch=fake_dispatch,
    )

    assert result["success"] is True
    assert sent["json"]["message"].startswith("FOUNDER EMAIL RECEIVED.")
    assert sent["dispatch_body"] == "Handled. I have it."
    assert sent["dispatch_sender"] == "aifusionlabs@gmail.com"


def test_load_state_defaults_when_missing(monkeypatch, tmp_path):
    from tools import founder_inbox_watcher

    monkeypatch.setattr(founder_inbox_watcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(founder_inbox_watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(founder_inbox_watcher, "EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(founder_inbox_watcher, "PID_PATH", tmp_path / "watcher.pid")

    state = founder_inbox_watcher.load_state()
    assert state["status"] == "idle"
    assert state["processed_ids"] == []


def test_save_state_round_trips(monkeypatch, tmp_path):
    from tools import founder_inbox_watcher

    monkeypatch.setattr(founder_inbox_watcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(founder_inbox_watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(founder_inbox_watcher, "EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(founder_inbox_watcher, "PID_PATH", tmp_path / "watcher.pid")

    founder_inbox_watcher.save_state({"running": True, "status": "active", "processed_ids": ["abc"]})
    with open(tmp_path / "state.json", "r", encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["status"] == "active"
    assert saved["processed_ids"] == ["abc"]


def test_founder_sender_matches_rejects_sloane_account():
    from tools.founder_inbox_watcher import founder_sender_matches

    assert founder_sender_matches("aifusionlabs@gmail.com") is True
    assert founder_sender_matches("novaaifusionlabs@gmail.com") is False
