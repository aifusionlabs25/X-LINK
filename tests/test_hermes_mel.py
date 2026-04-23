import json

from tools import hermes_mel
from tools.xagent_eval.batch_runner import aggregate_batch
from tools.xagent_eval.schemas import BatchSummary, CategoryScore, EvalInputs, Scorecard


def test_build_batch_plan_mixes_core_and_adaptive(monkeypatch):
    monkeypatch.setattr(hermes_mel, "_hermes_api_payload", lambda messages: None)
    monkeypatch.setattr(hermes_mel, "_ollama_json_generation", lambda prompt, model="qwen2.5:14b-instruct-q6_K": None)

    scenarios, manifest = hermes_mel.build_batch_plan(
        agent_slug="amy",
        scenario_pack="amy_it_discovery",
        difficulty="mixed",
        count=4,
        seed=7,
    )

    assert len(scenarios) == 4
    assert manifest["source_counts"]["canonical"] >= 1
    assert manifest["source_counts"]["hermes_adaptive"] >= 1
    assert all(item.get("pack_class") in {"core", "adaptive"} for item in scenarios)
    assert all(item.get("source") in {"canonical", "hermes_adaptive"} for item in scenarios)


def test_build_batch_plan_for_amy_prefers_frontdoor_core_in_mixed_mode(monkeypatch):
    monkeypatch.setattr(hermes_mel, "_hermes_api_payload", lambda messages: None)
    monkeypatch.setattr(hermes_mel, "_ollama_json_generation", lambda prompt, model="qwen2.5:14b-instruct-q6_K": None)

    scenarios, manifest = hermes_mel.build_batch_plan(
        agent_slug="amy",
        scenario_pack="amy_frontdoor_discovery",
        difficulty="mixed",
        count=3,
        seed=11,
    )

    core_ids = {
        item.get("scenario_id")
        for item in scenarios
        if item.get("source") == "canonical"
    }

    assert "AMY_SECURITY_REASSURANCE" not in core_ids
    assert any(item.get("source") == "canonical" for item in scenarios)
    assert manifest["source_counts"]["canonical"] >= 1


def test_persist_batch_manifest_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes_mel, "MEL_DIR", tmp_path / "mel")

    manifest = {
        "manifest_id": "mel_manifest_test",
        "agent_slug": "amy",
        "source_counts": {"canonical": 2, "hermes_adaptive": 1},
        "pack_class_counts": {"core": 2, "adaptive": 1},
        "scenarios": [],
    }

    path = hermes_mel.persist_batch_manifest(manifest, batch_id="batch123")

    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    assert payload["manifest_id"] == "mel_manifest_test"
    assert payload["source_counts"]["canonical"] == 2


def test_aggregate_batch_carries_manifest_metadata():
    inputs = EvalInputs(
        target_agent="amy",
        scenario_pack="amy_it_discovery",
        scenario_pack_class="adaptive",
        scenario_manifest_id="mel_manifest_123",
        scenario_manifest_path="vault/mel/batches/mel_manifest_123.json",
    )
    scorecard = Scorecard(
        run_id="r1",
        scenario_id="s1",
        target_agent="amy",
        overall_score=82.0,
        pass_fail="PASS",
        categories=[CategoryScore(key="loop_avoidance", label="Loop Avoidance", score=4, weight=15)],
    )

    summary = aggregate_batch("batch1", inputs, [scorecard], ["r1"])

    assert summary.scenario_pack_class == "adaptive"
    assert summary.scenario_manifest_id == "mel_manifest_123"
    assert summary.scenario_manifest_path.endswith("mel_manifest_123.json")
