from datetime import datetime, timedelta


def test_record_llm_call_and_summary(monkeypatch, tmp_path):
    from tools import telemetry

    monkeypatch.setattr(telemetry, "TELEMETRY_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "LLM_CALLS_PATH", tmp_path / "llm_calls.jsonl")
    monkeypatch.setattr(telemetry, "WORKFLOW_RUNS_PATH", tmp_path / "workflow_runs.jsonl")
    monkeypatch.setattr(telemetry, "GPU_SAMPLES_PATH", tmp_path / "gpu_samples.jsonl")

    started_at = datetime(2026, 4, 6, 12, 0, 0)
    ended_at = started_at + timedelta(seconds=2.5)

    telemetry.record_llm_call(
        workflow="sloane_runtime",
        provider="ollama",
        model="qwen-test",
        started_at=started_at,
        ended_at=ended_at,
        input_tokens_est=120,
        output_tokens_est=80,
        success=True,
        metadata={"target": "sloane"},
    )
    telemetry.record_workflow_run(
        workflow="mel_evolution",
        run_id="mel_run_1",
        status="complete",
        started_at=started_at,
        ended_at=ended_at,
        metadata={"agent": "dani"},
    )
    monkeypatch.setattr(
        telemetry.subprocess,
        "check_output",
        lambda *args, **kwargs: "NVIDIA GeForce RTX 5080, 21, 17, 16303, 12477, 55.05, 46",
    )
    telemetry.capture_gpu_sample(workflow="mel_batch_eval", run_id="mel_run_1", metadata={"agent": "dani"})

    summary = telemetry.get_telemetry_summary()
    assert summary["llm_calls"]["count"] == 1
    assert summary["llm_calls"]["input_tokens_est"] == 120
    assert summary["llm_calls"]["output_tokens_est"] == 80
    assert "ollama::qwen-test" in summary["llm_calls"]["by_model"]
    assert summary["workflows"]["by_workflow"]["mel_evolution"]["runs"] == 1
    assert summary["coverage"]["token_status"] == "partial"
    assert len(summary["gpu"]["recent_samples"]) == 1


def test_runtime_logs_ollama_telemetry(monkeypatch):
    from tools import sloane_runtime

    logged = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "Hello from local model."}

    def fake_post(*args, **kwargs):
        return FakeResponse()

    def fake_record_llm_call(**kwargs):
        logged.update(kwargs)
        return kwargs

    monkeypatch.setattr(sloane_runtime.requests, "post", fake_post)
    monkeypatch.setattr(sloane_runtime, "record_llm_call", fake_record_llm_call)
    monkeypatch.setattr(sloane_runtime, "capture_gpu_sample", lambda **kwargs: None)

    result = sloane_runtime._generate_with_ollama("Hello world", {"model": "qwen-test"})

    assert result["provider"] == "ollama"
    assert logged["workflow"] == "sloane_runtime"
    assert logged["provider"] == "ollama"
    assert logged["model"] == "qwen-test"
    assert logged["input_tokens_est"] > 0
