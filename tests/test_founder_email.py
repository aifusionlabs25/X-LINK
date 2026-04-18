import asyncio


def test_extract_founder_reply_request_parses_natural_language():
    from tools.founder_email import extract_founder_reply_request

    req = extract_founder_reply_request("Reply to my last email and say I'm on it.")
    assert req == {
        "sender": "aifusionlabs@gmail.com",
        "body": "I'm on it.",
    }


def test_extract_founder_reply_request_defaults_to_acknowledgement():
    from tools.founder_email import DEFAULT_ACK_BODY, extract_founder_reply_request

    req = extract_founder_reply_request("Can you reply to my latest email?")
    assert req == {
        "sender": "aifusionlabs@gmail.com",
        "body": DEFAULT_ACK_BODY,
    }


def test_dispatch_founder_reply_rejects_non_founder_sender():
    from tools.founder_email import dispatch_founder_reply

    res = dispatch_founder_reply("Noted.", sender="someone@example.com")
    assert res["success"] is False
    assert "locked to aifusionlabs@gmail.com" in res["stderr"]


def test_chat_bridge_handles_founder_reply_fast_path(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    monkeypatch.setattr(
        synapse_bridge,
        "dispatch_founder_reply",
        lambda body, sender="aifusionlabs@gmail.com": {
            "success": True,
            "stdout": "Reply sent to aifusionlabs@gmail.com successfully.",
            "stderr": "",
            "returncode": 0,
        },
    )

    result = asyncio.run(
        synapse_bridge.chat_with_sloane(
            {"message": "Reply to my last email and say I saw it and I'm handling it."}
        )
    )

    assert result["agent"] == "Sloane"
    assert result["reply"] == "Done. I replied to your latest email."


def test_chat_bridge_forwarded_founder_email_uses_digest_path(monkeypatch):
    from tools import synapse_bridge

    synapse_bridge.chat_history = []
    digest_called = {"count": 0}

    def fake_build_digest(target_date, recipient):
        digest_called["count"] += 1
        return {
            "subject": "Digest",
            "body": "Rob,\n\nHere is the test-session digest.\n\nSloane",
            "count": 1,
            "jobs": [],
        }

    import tools.sloane_jobs as sloane_jobs
    monkeypatch.setattr(sloane_jobs, "build_test_session_digest", fake_build_digest)
    result = asyncio.run(
        synapse_bridge.chat_with_sloane(
            {
                "message": (
                    "FOUNDER EMAIL RECEIVED.\n"
                    "Sender: aifusionlabs@gmail.com\n"
                    "Subject: Test\n"
                    "Body:\nI need a list of all test sessions performed for 4.4.26."
                )
            }
        )
    )

    assert digest_called["count"] == 1
    assert result["agent"] == "Sloane"
    assert "test-session digest" in result["reply"].lower()


def test_chat_bridge_digest_send_me_defaults_to_founder_email(monkeypatch):
    from tools import synapse_bridge
    import tools.sloane_jobs as sloane_jobs

    synapse_bridge.chat_history = []

    monkeypatch.setattr(
        sloane_jobs,
        "build_test_session_digest",
        lambda target_date, recipient: {
            "subject": "Digest",
            "body": "Digest body",
            "count": 1,
            "jobs": [],
            "recipient": recipient,
        },
    )
    dispatch_log = {}
    monkeypatch.setattr(
        sloane_jobs,
        "_dispatch_email",
        lambda subject, body, recipient: dispatch_log.update({"recipient": recipient}) or {"success": True},
    )

    result = asyncio.run(
        synapse_bridge.chat_with_sloane(
            {"message": "Send me an email with the list of all test sessions from 4.4.26 and include your short take on each one"}
        )
    )

    assert dispatch_log["recipient"] == "aifusionlabs@gmail.com"
    assert "aifusionlabs@gmail.com" in result["reply"]


def test_chat_bridge_digest_resend_uses_recent_requested_date(monkeypatch):
    from tools import synapse_bridge
    import tools.sloane_jobs as sloane_jobs

    synapse_bridge.chat_history = [
        {"role": "user", "content": "Send me an email with the list of all test sessions from 4.4.26 and include your short take on each one"},
        {"role": "assistant", "content": "Understood. I sent the April 04, 2026 test-session digest to novaaifusionlabs@gmail.com."},
    ]

    monkeypatch.setattr(
        sloane_jobs,
        "build_test_session_digest",
        lambda target_date, recipient: {
            "subject": "Digest",
            "body": "Digest body",
            "count": 1,
            "jobs": [],
            "recipient": recipient,
        },
    )
    dispatch_log = {}
    monkeypatch.setattr(
        sloane_jobs,
        "_dispatch_email",
        lambda subject, body, recipient: dispatch_log.update({"recipient": recipient}) or {"success": True},
    )

    result = asyncio.run(synapse_bridge.chat_with_sloane({"message": "send to aifusionlabs@gmail.com"}))

    assert dispatch_log["recipient"] == "aifusionlabs@gmail.com"
    assert "aifusionlabs@gmail.com" in result["reply"]


def test_chat_bridge_anam_usage_email_fast_path(monkeypatch):
    from tools import synapse_bridge
    import tools.site_report_workflows as site_report_workflows

    synapse_bridge.chat_history = []
    call_log = {}

    async def fake_run(site_key, days=7, recipient="aifusionlabs@gmail.com"):
        call_log["site_key"] = site_key
        call_log["days"] = days
        call_log["recipient"] = recipient
        return {"success": True, "email": {"success": True}}

    monkeypatch.setattr(site_report_workflows, "run_site_usage_email_report", fake_run)

    result = asyncio.run(
        synapse_bridge.chat_with_sloane(
            {
                "message": "Please check the usage for Anam site for last 7 days and send me an email with a report and screenshots of the graphs."
            }
        )
    )

    assert call_log["site_key"] == "anam"
    assert call_log["days"] == 7
    assert call_log["recipient"] == "aifusionlabs@gmail.com"
    assert "sent the 7-day report" in result["reply"].lower()
