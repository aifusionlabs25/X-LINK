import asyncio
import json


def test_hermes_executor_blocks_unknown_action():
    from tools.hermes_executor import HermesActionExecutor

    executor = HermesActionExecutor(root_dir="C:/tmp", python_exe="python")

    try:
        executor.execute("FORMAT_DRIVE", {}, {})
    except ValueError as exc:
        assert "blocked unsupported action" in str(exc)
    else:
        raise AssertionError("Expected executor to block unknown action")


def test_hermes_executor_blocks_outbound_email_when_policy_disabled():
    from tools.hermes_executor import HermesActionExecutor, HermesExecutionPolicy

    executor = HermesActionExecutor(
        root_dir="C:/tmp",
        python_exe="python",
        policy=HermesExecutionPolicy(allow_outbound_email=False),
    )

    result = executor.execute(
        "GSUITE_INTENT",
        {"intent": "gmail_send", "target": "test@example.com", "subject": "Hello", "body": "Body"},
        {},
    )

    assert "blocked outbound Gmail send" in result["reply"]


def test_chat_bridge_routes_gmail_list_through_hermes_executor(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []

    monkeypatch.setattr(
        synapse_bridge,
        "generate_sloane_response",
        lambda **kwargs: {
            "text": 'X_LINK_CALL {"action": "GSUITE_INTENT", "args": {"intent": "gmail_list", "target": "novaaifusionlabs@gmail.com", "limit": 3}}'
        },
    )
    monkeypatch.setattr(
        synapse_bridge.HERMES_EXECUTOR,
        "execute",
        lambda action, args, context=None: {
            "reply": "Yes. I checked the inbox. The latest message is from aifusionlabs@gmail.com with subject 'Founder note'. I can see 1 recent message.",
            "gmail_list": {"success": True, "count": 1, "entries": [{"subject": "Founder note"}]},
        },
    )

    result = asyncio.run(synapse_bridge.chat_with_hermes({"message": "Have you checked your email recently?"}))

    assert result["agent"] == "Hermes"
    assert "checked the inbox" in result["reply"]
    assert result["gmail_list"]["count"] == 1


def test_hermes_executor_launches_background_audit(monkeypatch):
    from tools.hermes_executor import HermesActionExecutor

    launch_log = {}

    class DummyProc:
        pid = 4321

    monkeypatch.setattr(
        "tools.hermes_executor.subprocess.Popen",
        lambda args, cwd=None: launch_log.update({"args": args, "cwd": cwd}) or DummyProc(),
    )

    executor = HermesActionExecutor(root_dir="C:/repo", python_exe="python")
    result = executor.execute("EXEC_AUDIT", {}, {"user_msg": "check for Google in our usage auditor"})

    assert "check for Google" in result["reply"]
    assert result["pid"] == 4321
    assert launch_log["args"][1].endswith("tools/usage_auditor.py")


def test_hermes_executor_archive_writes_request_payload(monkeypatch, tmp_path):
    from tools.hermes_executor import HermesActionExecutor

    launch_log = {}

    class DummyProc:
        pid = 8765

    monkeypatch.setattr(
        "tools.hermes_executor.subprocess.Popen",
        lambda args, cwd=None: launch_log.update({"args": args, "cwd": cwd}) or DummyProc(),
    )

    executor = HermesActionExecutor(root_dir=str(tmp_path), python_exe="python")
    result = executor.execute(
        "EXEC_ARCHIVE",
        {},
        {"user_msg": 'pull the last 10 ChatGPT chats from "X Agents" and produce an executive digest'},
    )

    run_dir = tmp_path / "vault" / "archives" / "_runs" / result["run_id"]
    payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))

    assert payload["platform"] == "chatgpt"
    assert payload["folder_name"] == "X Agents"
    assert payload["limit"] == "10"
    assert "X Agents" in result["reply"]
    assert launch_log["args"][1].replace("\\", "/").endswith("tools/great_archivist.py")


def test_hermes_executor_archive_retry_inherits_folder_from_chat_history(monkeypatch, tmp_path):
    from tools.hermes_executor import HermesActionExecutor

    monkeypatch.setattr(
        "tools.hermes_executor.subprocess.Popen",
        lambda args, cwd=None: type("DummyProc", (), {"pid": 2468})(),
    )

    executor = HermesActionExecutor(root_dir=str(tmp_path), python_exe="python")
    result = executor.execute(
        "EXEC_ARCHIVE",
        {},
        {
            "user_msg": "try again I helped you and selected the correct Project folder.",
            "chat_history": [
                {
                    "role": "user",
                    "content": "archive the last 10 chatgpt sessions located in the Projects folder named 'X Agents'.",
                }
            ],
        },
    )

    run_dir = tmp_path / "vault" / "archives" / "_runs" / result["run_id"]
    payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))

    assert payload["folder_name"] == "X Agents"
    assert "X Agents" in result["reply"]


def test_chat_bridge_parses_tool_call_with_trailing_text(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    monkeypatch.setattr(
        synapse_bridge,
        "generate_sloane_response",
        lambda **kwargs: {
            "text": (
                'X_LINK_CALL {"action": "EXEC_AUDIT", "args": {}}\n\n'
                "Afterwards: here is extra analysis that should be ignored."
            )
        },
    )
    monkeypatch.setattr(
        synapse_bridge.HERMES_EXECUTOR,
        "execute",
        lambda action, args, context=None: {"reply": "I've dispatched the usage audit.", "pid": 99},
    )

    result = asyncio.run(synapse_bridge.chat_with_hermes({"message": "Check the usage auditor."}))

    assert result["reply"] == "I've dispatched the usage audit."
    assert result["pid"] == 99


def test_chat_bridge_checks_subscription_card_without_model(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    monkeypatch.setattr(
        synapse_bridge,
        "find_subscription_card",
        lambda platform: {"platform": "Google", "cost": "$9.99", "renewal_date": "Apr 10, 2026"},
    )

    result = asyncio.run(
        synapse_bridge.chat_with_hermes({"message": "check and see if we have a card for Google in our Usage Auditor"})
    )

    assert result["agent"] == "Hermes"
    assert "already has a Google card" in result["reply"]
    assert "$9.99" in result["reply"]


def test_chat_bridge_adds_subscription_card_from_email_fast_path(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    monkeypatch.setattr(
        synapse_bridge,
        "_read_latest_subscription_email",
        lambda platform: {
            "success": True,
            "sender": "rvicks@gmail.com",
            "subject": "Fwd: Your Google Play Order Receipt from Apr 10, 2026",
            "body": "Total: $9.99\nOrder date: Apr 10, 2026",
        },
    )
    saved = {}
    monkeypatch.setattr(
        synapse_bridge,
        "upsert_subscription_card",
        lambda platform, fields, source="": saved.update({"platform": platform, **fields}) or {"platform": platform, **fields},
    )

    result = asyncio.run(
        synapse_bridge.chat_with_hermes({"message": "yes please add a new card for the Google sub, use details for amount and bill date from email I sent to you."})
    )

    assert result["agent"] == "Hermes"
    assert "added the Google card" in result["reply"]
    assert saved["cost"] == "$9.99"


def test_chat_bridge_inbox_check_fast_path(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    monkeypatch.setattr(
        synapse_bridge.HERMES_EXECUTOR,
        "execute",
        lambda action, args, context=None: {
            "reply": "Yes. I checked the inbox. The latest message is from rvicks@gmail.com with subject 'Receipt'. I can see 1 recent message.",
            "gmail_list": {"success": True, "count": 1, "entries": [{"subject": "Receipt"}]},
        },
    )

    result = asyncio.run(synapse_bridge.chat_with_hermes({"message": "read email please"}))

    assert result["agent"] == "Hermes"
    assert "checked the inbox" in result["reply"]
    assert result["gmail_list"]["count"] == 1


def test_chat_bridge_inbox_detail_followup_fast_path(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    synapse_bridge.last_inbox_lookup = {
        "account": "novaaifusionlabs@gmail.com",
        "sender": "rvicks@gmail.com",
        "subject": "Fwd: Your Google Play Order Receipt from Apr 10, 2026",
        "summary": "Order receipt summary",
        "count": 1,
    }

    monkeypatch.setattr(
        synapse_bridge.HERMES_EXECUTOR,
        "execute",
        lambda action, args, context=None: {
            "reply": "I pulled the latest matching email from rvicks@gmail.com with subject 'Fwd: Your Google Play Order Receipt from Apr 10, 2026'.",
            "gmail_read_latest": {
                "success": True,
                "sender": "rvicks@gmail.com",
                "subject": "Fwd: Your Google Play Order Receipt from Apr 10, 2026",
                "body": "Total charged: $9.99\nOrder date: Apr 10, 2026\nOrder number: GPA.1234-5678-9012-34567",
                "body_preview": "Total charged: $9.99",
            },
        },
    )

    result = asyncio.run(synapse_bridge.chat_with_hermes({"message": "what did the email say , I need all details"}))

    assert result["agent"] == "Hermes"
    assert "Total charged: $9.99" in result["reply"]
    assert result["gmail_read_latest"]["success"] is True


def test_legacy_sloane_chat_alias_routes_to_hermes(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    
    async def _fake_chat(payload):
        return {"reply": "Hermes handled it.", "agent": "Hermes"}

    monkeypatch.setattr(
        synapse_bridge,
        "chat_with_hermes",
        _fake_chat,
    )

    result = asyncio.run(synapse_bridge.chat_with_sloane({"message": "status?"}))

    assert result["agent"] == "Hermes"
    assert "Hermes handled it." in result["reply"]
