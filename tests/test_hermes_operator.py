def test_plan_operator_mission_builds_test_session_plan():
    from tools.hermes_operator import plan_operator_mission

    plan = plan_operator_mission(
        "Run an Amy SH Lab and X Agent Eval cycle.",
        {"requested_by": "Rob", "persona": "sloane", "target_agent": "amy"},
    )

    assert plan["owner_agent"] == "hermes"
    assert plan["intent"] == "test_session_create"
    assert plan["requested_by"] == "Rob"
    assert plan["target_agent"] == "amy"
    assert plan["plan_steps"][0]["key"] == "preflight"
    assert plan["rollback_checkpoint"]["recommended"] is True


def test_normalize_job_to_mission_preserves_legacy_surface():
    from tools.hermes_operator import normalize_job_to_mission

    job = {
        "job_id": "sloane_test_123",
        "phase": "running",
        "status": "running",
        "spec": {"target_agent": "amy"},
        "steps": {
            "preflight": {"status": "done"},
            "sh_lab": {"status": "running"},
        },
        "artifacts": {"report_text": "C:/tmp/report.txt"},
        "results": {},
        "errors": [],
    }

    mission = normalize_job_to_mission(job)

    assert mission["mission_id"] == "sloane_test_123"
    assert mission["owner_agent"] == "hermes"
    assert mission["status"] == "running"
    assert mission["job_id"] == "sloane_test_123"
    assert mission["phase"] == "running"
    assert mission["spec"]["target_agent"] == "amy"
    assert mission["active_step"] == "sh_lab"


def test_execute_operator_plan_creates_job_and_normalizes(monkeypatch):
    from tools import hermes_operator

    created_job = {
        "job_id": "sloane_test_abc123",
        "phase": "planning",
        "status": "running",
        "spec": {"target_agent": "dani", "email_policy": {"recipient": "aifusionlabs@gmail.com"}},
        "steps": {"preflight": {"status": "pending"}},
        "artifacts": {},
        "results": {},
        "errors": [],
    }

    monkeypatch.setattr("tools.sloane_jobs.create_test_operator_job", lambda mission_request, params: dict(created_job))
    monkeypatch.setattr(
        "tools.sloane_jobs.start_job",
        lambda job_id: {**created_job, "phase": "planning", "runtime": {"worker_pid": 1234}},
    )
    monkeypatch.setattr(hermes_operator, "remember_mission_state", lambda mission_state: mission_state)
    monkeypatch.setattr(hermes_operator, "remember_rollback_checkpoint", lambda checkpoint: checkpoint)

    plan = hermes_operator.plan_operator_mission(
        "Run a Dani mission.",
        {"requested_by": "Rob", "persona": "sloane", "target_agent": "dani", "intent_hint": "test_session_create"},
    )
    result = hermes_operator.execute_operator_plan(
        plan,
        {"args": {"target_agent": "dani", "recipient": "aifusionlabs@gmail.com"}, "start": True},
    )

    assert result["status"] == "running"
    assert result["job_id"] == "sloane_test_abc123"
    assert result["mission"]["owner_agent"] == "hermes"
    assert "Mission dispatched" in result["reply_hint"]


def test_render_operator_reply_uses_reply_hint():
    from tools.hermes_operator import render_operator_reply

    reply = render_operator_reply({"reply_hint": "Mission dispatched. Test Operator job abc is now planning."}, persona="sloane")

    assert reply == "Mission dispatched. Test Operator job abc is now planning."
