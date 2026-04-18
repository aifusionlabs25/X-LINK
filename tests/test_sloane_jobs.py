import json
import os
import sys
from pathlib import Path


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


def test_create_test_operator_job_uses_controlled_email_policy(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "Dani", "recipient": "aifusionlabs@gmail.com"},
    )

    assert job["spec"]["target_agent"] == "dani"
    assert job["spec"]["email_policy"]["sender"] == "novaaifusionlabs@gmail.com"
    assert job["spec"]["email_policy"]["auto_send"] is True
    assert job["spec"]["validation_profile"]["family"] == "sales_discovery"
    assert job["spec"]["eval"]["batch_id"] == f"{job['job_id']}/eval"
    assert (tmp_path / "jobs" / f"{job['job_id']}.json").exists()


def test_create_test_operator_job_requires_approval_for_other_recipients(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "dani", "recipient": "rob@example.com"},
    )

    assert job["spec"]["email_policy"]["auto_send"] is False
    assert job["spec"]["email_policy"]["requires_approval"] is True


def test_create_test_operator_job_respects_sh_lab_only_language(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani SH Lab batch then send the report to aifusionlabs@gmail.com.",
        {"target_agent": "dani", "recipient": "aifusionlabs@gmail.com"},
    )

    assert job["spec"]["run_sh_lab"] is True
    assert job["spec"]["run_xagent_eval"] is False


def test_parse_requested_date_supports_short_dot_format():
    from tools import sloane_jobs

    parsed = sloane_jobs.parse_requested_date("4.4.26")
    assert str(parsed) == "2026-04-04"


def test_build_test_session_digest_lists_matching_jobs(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "dani", "recipient": "aifusionlabs@gmail.com"},
    )
    job["created_at"] = "2026-04-04T22:55:52.428334"
    job["phase"] = "completed"
    job["results"]["sh_lab"] = {"baseline": {"score": 72.0}}
    job["results"]["release_readiness"] = {"recommendation": "revise"}
    sloane_jobs.save_job(job)

    digest = sloane_jobs.build_test_session_digest(sloane_jobs.parse_requested_date("4.4.26"), "aifusionlabs@gmail.com")
    assert digest["count"] == 1
    assert job["job_id"] in digest["body"]
    assert "Total sessions: 1" in digest["body"]
    assert "My quick read:" in digest["body"]
    assert "Session details:" in digest["body"]


def test_approve_job_email_dispatches_waiting_report(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "dani", "recipient": "reviewer@example.com"},
    )
    job["phase"] = "waiting_for_approval"
    job["status"] = "waiting_for_approval"
    job["results"]["email"] = {
        "sender": "novaaifusionlabs@gmail.com",
        "recipient": "reviewer@example.com",
        "subject": "Subject",
        "body": "Body",
        "status": "pending",
        "requires_approval": True,
    }
    sloane_jobs.save_job(job)

    monkeypatch.setattr(
        sloane_jobs,
        "_dispatch_email",
        lambda subject, body, recipient: {
            "returncode": 0,
            "stdout": "sent",
            "stderr": "",
            "sent_at": "2026-04-04T12:00:00",
        },
    )

    approved = sloane_jobs.approve_job_email(job["job_id"])
    assert approved["phase"] == "completed"
    assert approved["results"]["email"]["status"] == "sent"
    assert approved["steps"]["email"]["status"] == "done"


def test_email_dispatch_failure_output_is_not_treated_as_sent(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "dani", "recipient": "reviewer@example.com"},
    )
    job["phase"] = "waiting_for_approval"
    job["status"] = "waiting_for_approval"
    job["results"]["email"] = {
        "sender": "novaaifusionlabs@gmail.com",
        "recipient": "reviewer@example.com",
        "subject": "Subject",
        "body": "Body",
        "status": "pending",
        "requires_approval": True,
    }
    sloane_jobs.save_job(job)

    monkeypatch.setattr(
        sloane_jobs,
        "_dispatch_email",
        lambda subject, body, recipient: {
            "returncode": 0,
            "stdout": "Failed to connect to browser.",
            "stderr": "",
            "sent_at": "2026-04-05T08:00:00",
            "success": False,
        },
    )

    approved = sloane_jobs.approve_job_email(job["job_id"])
    assert approved["phase"] == "failed"
    assert approved["results"]["email"]["status"] == "failed"
    assert approved["steps"]["email"]["status"] == "error"


def test_email_dispatch_success_tolerates_asyncio_cleanup_noise(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "dani", "recipient": "reviewer@example.com"},
    )
    job["phase"] = "waiting_for_approval"
    job["status"] = "waiting_for_approval"
    job["results"]["email"] = {
        "sender": "novaaifusionlabs@gmail.com",
        "recipient": "reviewer@example.com",
        "subject": "Subject",
        "body": "Body",
        "status": "pending",
        "requires_approval": True,
    }
    sloane_jobs.save_job(job)

    monkeypatch.setattr(
        sloane_jobs,
        "_dispatch_email",
        lambda subject, body, recipient: {
            "returncode": 0,
            "stdout": "Gmail sent to reviewer@example.com successfully.",
            "stderr": "Exception ignored in: <function BaseSubprocessTransport.__del__ at 0x123>\nRuntimeError: Event loop is closed",
            "sent_at": "2026-04-05T08:10:00",
        },
    )

    approved = sloane_jobs.approve_job_email(job["job_id"])
    assert approved["phase"] == "completed"
    assert approved["results"]["email"]["status"] == "sent"
    assert approved["steps"]["email"]["status"] == "done"


def test_approve_job_email_can_resend_completed_report(monkeypatch, tmp_path):
    from tools import sloane_jobs
    captured = {}

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job(
        "Run a Dani mission",
        {"target_agent": "dani", "recipient": "reviewer@example.com"},
    )
    job["phase"] = "completed"
    job["status"] = "completed"
    mel_summary_path = tmp_path / "mel_summary.json"
    mel_summary_path.write_text(
        json.dumps(
            {
                "average_score": 76.0,
                "pass_rate": 50.0,
                "verdict": "NO_SHIP",
                "top_failure_categories": ["flow_naturalness"],
                "runs": [{"harness_artifacts": []}],
            }
        ),
        encoding="utf-8",
    )
    job["results"]["sh_lab"] = {"batch_summary_path": str(mel_summary_path)}
    job["results"]["email"] = {
        "sender": "novaaifusionlabs@gmail.com",
        "recipient": "reviewer@example.com",
        "subject": "Subject",
        "body": "Body",
        "status": "failed",
        "requires_approval": True,
    }
    sloane_jobs.save_job(job)

    monkeypatch.setattr(
        sloane_jobs,
        "_dispatch_email",
        lambda subject, body, recipient: captured.update({"subject": subject, "body": body, "recipient": recipient}) or {
            "returncode": 0,
            "stdout": "sent",
            "stderr": "",
            "sent_at": "2026-04-05T08:05:00",
            "success": True,
        },
    )

    resent = sloane_jobs.approve_job_email(job["job_id"])
    assert resent["phase"] == "completed"
    assert resent["results"]["email"]["status"] == "sent"
    assert resent["steps"]["email"]["status"] == "done"
    assert "I've finished the latest Dani test run." in captured["body"]


def test_save_report_persists_text_and_json(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job("Run a Dani mission", {"target_agent": "dani"})
    job["results"]["sh_lab"] = {"batch_summary_path": "C:\\temp\\mel.json"}
    job["results"]["xagent_eval"] = {"summary": {"average_score": 61.0, "pass_rate": 0.0, "verdict": "FAIL"}}

    subject = "Report Subject"
    body = "Report Body"
    sloane_jobs._save_report(job, subject, body)

    report_json = Path(job["artifacts"]["report_json"])
    report_text = Path(job["artifacts"]["report_text"])
    assert report_json.exists()
    assert report_text.exists()
    assert json.loads(report_json.read_text(encoding="utf-8"))["subject"] == subject
    assert report_text.read_text(encoding="utf-8") == body


def test_compose_report_includes_release_readiness(monkeypatch, tmp_path):
    from tools import sloane_jobs

    monkeypatch.setattr(sloane_jobs, "SLOANE_DIR", tmp_path)
    monkeypatch.setattr(sloane_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sloane_jobs, "REPORTS_DIR", tmp_path / "reports")

    job = sloane_jobs.create_test_operator_job("Run a Dani mission", {"target_agent": "dani"})
    mel_summary_path = tmp_path / "mel_summary.json"
    mel_summary_path.write_text(
        json.dumps(
            {
                "average_score": 76.0,
                "pass_rate": 50.0,
                "verdict": "NO_SHIP",
                "top_failure_categories": ["flow_naturalness"],
                "runs": [{"harness_artifacts": []}],
            }
        ),
        encoding="utf-8",
    )
    job["results"]["sh_lab"] = {"batch_summary_path": str(mel_summary_path)}
    subject_body = sloane_jobs._compose_report(job)

    assert "Validation Family: Sales / Discovery" in subject_body["body"]
    assert "Release Gates:" in subject_body["body"]
    assert "I've finished the latest Dani test run." in subject_body["email_body"]
    assert "What stands out:" in subject_body["email_body"]
    assert "My recommendation is to soft launch" in subject_body["email_body"]
    assert job["results"]["release_readiness"]["recommendation"] == "soft_launch"
