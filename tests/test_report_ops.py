from pathlib import Path


def test_build_report_artifacts_creates_expected_keys(tmp_path):
    from tools.report_ops import build_report_artifacts

    artifacts = build_report_artifacts(Path(tmp_path), "anam_usage", ("dashboard", "sessions"))

    assert "report_json" in artifacts
    assert "report_text" in artifacts
    assert "dashboard_screenshot" in artifacts
    assert "sessions_screenshot" in artifacts
    assert artifacts["report_json"].endswith(".json")
    assert artifacts["dashboard_screenshot"].endswith("_dashboard.png")


def test_write_report_bundle_writes_json_and_text(tmp_path):
    from tools.report_ops import write_report_bundle

    json_path = tmp_path / "report.json"
    text_path = tmp_path / "report.txt"
    write_report_bundle(str(json_path), str(text_path), {"ok": True}, "hello")

    assert json_path.exists()
    assert text_path.exists()
    assert '"ok": true' in json_path.read_text(encoding="utf-8").lower()
    assert text_path.read_text(encoding="utf-8") == "hello"


def test_identify_site_report_request_matches_anam():
    from tools.site_report_workflows import identify_site_report_request

    site_key = identify_site_report_request(
        "Please check the usage for Anam site for last 7 days and send me an email report with screenshots."
    )

    assert site_key == "anam"


def test_dispatch_report_email_forwards_attachments(monkeypatch):
    from tools import report_ops

    log = {}

    monkeypatch.setattr(
        "tools.sloane_jobs._dispatch_email",
        lambda subject, body, recipient, attachments=None: log.update(
            {"subject": subject, "recipient": recipient, "attachments": attachments}
        ) or {"success": True},
    )

    result = report_ops.dispatch_report_email(
        "Subject",
        "Body",
        "aifusionlabs@gmail.com",
        attachments=["one.png", "two.png"],
    )

    assert result["success"] is True
    assert log["recipient"] == "aifusionlabs@gmail.com"
    assert log["attachments"] == ["one.png", "two.png"]


def test_extract_anam_overview_metrics_prefers_totals_over_generic_years():
    from tools.site_report_workflows import _extract_anam_overview_metrics

    text = """
    Latest session: April 4, 2026
    Session Activity Last 7 days Daily breakdown
    Total Sessions 218
    Minutes Used Last 7 days Daily breakdown
    Total Usage 9h 5m
    """

    metrics = _extract_anam_overview_metrics(text)

    assert metrics["total_sessions"] == "218"
    assert metrics["total_usage"] == "9h 5m"
    assert metrics["latest_session"] == "April 4, 2026"
    assert metrics["range_label"] == "Last 7 days"


def test_extract_anam_history_metrics_does_not_treat_year_as_session_count():
    from tools.site_report_workflows import _extract_anam_history_metrics

    text = """
    0 Active
    Latest session: April 4, 2026
    History Last 7 days
    """

    metrics = _extract_anam_history_metrics(text)

    assert metrics["active_sessions"] == "0"
    assert metrics["latest_session"] == "April 4, 2026"
    assert "sessions_listed" not in metrics


def test_compose_anam_report_is_concise_and_does_not_dump_local_artifact_paths():
    from tools.site_report_workflows import _compose_anam_report

    report = _compose_anam_report(
        7,
        "aifusionlabs@gmail.com",
        {"range_label": "Last 30 days", "total_sessions": "218", "total_usage": "9h 5m"},
        {"latest_session": "April 4, 2026", "active_sessions": "0"},
        {
            "overview_screenshot": r"C:\temp\overview.png",
            "history_screenshot": r"C:\temp\history.png",
            "report_json": r"C:\temp\report.json",
            "report_text": r"C:\temp\report.txt",
        },
    )

    body = report["body"]
    assert "Requested range: Last 7 days" in body
    assert "Actual range shown: Last 30 days" in body
    assert "Overview screenshot" in body
    assert r"C:\temp\overview.png" not in body
    assert r"C:\temp\report.json" not in body
