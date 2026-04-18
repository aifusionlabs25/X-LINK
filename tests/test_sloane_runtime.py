def test_runtime_status_defaults_to_ollama(monkeypatch):
    from tools import sloane_runtime

    monkeypatch.setattr(
        sloane_runtime,
        "load_runtime_config",
        lambda: {
            "runtime": {
                "default_provider": "auto",
                "fallback_provider": "ollama",
                "providers": {
                    "ollama": {"enabled": True, "model": "qwen"},
                    "hermes_api": {"enabled": False, "base_url": "http://127.0.0.1:8000", "model": "hermes"},
                },
            }
        },
    )
    monkeypatch.setattr(
        sloane_runtime,
        "_safe_get_json",
        lambda url, timeout=3, headers=None: {"version": "ok"} if "11434" in url else None,
    )

    status = sloane_runtime.get_runtime_status()
    assert status["active_provider"] == "ollama"
    assert status["providers"]["ollama"]["online"] is True
    assert status["providers"]["hermes_api"]["online"] is False


def test_runtime_prefers_hermes_when_online(monkeypatch):
    from tools import sloane_runtime

    monkeypatch.setattr(
        sloane_runtime,
        "load_runtime_config",
        lambda: {
            "runtime": {
                "default_provider": "auto",
                "fallback_provider": "ollama",
                "providers": {
                    "ollama": {"enabled": True, "model": "qwen"},
                    "hermes_api": {"enabled": True, "base_url": "http://127.0.0.1:8000", "model": "hermes"},
                },
            }
        },
    )
    monkeypatch.setattr(
        sloane_runtime,
        "_safe_get_json",
        lambda url, timeout=3, headers=None: {"data": [{"id": "hermes"}]},
    )
    monkeypatch.setattr(
        sloane_runtime,
        "_generate_with_hermes_api",
        lambda messages, cfg: {"provider": "hermes_api", "model": "hermes", "text": "Hermes handled this."},
    )
    monkeypatch.setattr(sloane_runtime, "build_hermes_grounding", lambda user_text: "[HERMES SKILLS]\n- Test")
    monkeypatch.setattr(
        sloane_runtime,
        "plan_operator_mission",
        lambda request, context=None: {"intent": "general_chat", "requested_by": "Rob", "plan_steps": []},
    )
    monkeypatch.setattr(sloane_runtime, "build_operator_grounding", lambda request, plan=None: "[HERMES PLAN]\n- intent: general_chat")
    monkeypatch.setattr(sloane_runtime, "remember_operator_action", lambda action, details=None, limit=40: None)

    res = sloane_runtime.generate_sloane_response(
        base_persona="System",
        chat_history=[{"role": "user", "content": "Hello"}],
        grounding_block="",
        target_name="Sloane",
    )
    assert res["provider"] == "hermes_api"
    assert res["text"] == "Hermes handled this."
    assert res["orchestrator"] == "hermes_core"
    assert res["mission_plan"]["intent"] == "general_chat"


def test_runtime_status_checks_hermes_with_inline_api_key(monkeypatch):
    from tools import sloane_runtime

    calls = []

    def fake_safe_get_json(url, timeout=3, headers=None):
        calls.append({"url": url, "timeout": timeout, "headers": headers})
        if "8642" in url:
            return {"data": [{"id": "hermes-agent"}]}
        if "11434" in url:
            return {"version": "0.20.2"}
        return None

    monkeypatch.setattr(
        sloane_runtime,
        "load_runtime_config",
        lambda: {
            "runtime": {
                "default_provider": "auto",
                "fallback_provider": "ollama",
                "providers": {
                    "ollama": {"enabled": True, "model": "qwen"},
                    "hermes_api": {
                        "enabled": True,
                        "base_url": "http://127.0.0.1:8642",
                        "model": "hermes-agent",
                        "api_key": "xlink-local-key",
                    },
                },
            }
        },
    )
    monkeypatch.setattr(sloane_runtime, "_safe_get_json", fake_safe_get_json)

    status = sloane_runtime.get_runtime_status()

    assert status["active_provider"] == "hermes_api"
    hermes_call = next(call for call in calls if "8642" in call["url"])
    assert hermes_call["headers"]["Authorization"] == "Bearer xlink-local-key"


def test_runtime_falls_back_to_ollama_when_hermes_errors(monkeypatch):
    from tools import sloane_runtime

    monkeypatch.setattr(
        sloane_runtime,
        "load_runtime_config",
        lambda: {
            "runtime": {
                "default_provider": "auto",
                "fallback_provider": "ollama",
                "providers": {
                    "ollama": {"enabled": True, "model": "qwen"},
                    "hermes_api": {"enabled": True, "base_url": "http://127.0.0.1:8000", "model": "hermes"},
                },
            }
        },
    )
    monkeypatch.setattr(
        sloane_runtime,
        "_safe_get_json",
        lambda url, timeout=3, headers=None: {"data": [{"id": "hermes"}]},
    )

    def boom(messages, cfg):
        raise RuntimeError("hermes down")

    monkeypatch.setattr(sloane_runtime, "_generate_with_hermes_api", boom)
    monkeypatch.setattr(
        sloane_runtime,
        "_generate_with_ollama",
        lambda prompt, cfg: {"provider": "ollama", "model": "qwen", "text": "Fallback reply"},
    )
    monkeypatch.setattr(sloane_runtime, "build_hermes_grounding", lambda user_text: "[HERMES SKILLS]\n- Test")
    monkeypatch.setattr(
        sloane_runtime,
        "plan_operator_mission",
        lambda request, context=None: {"intent": "general_chat", "requested_by": "Rob", "plan_steps": []},
    )
    monkeypatch.setattr(sloane_runtime, "build_operator_grounding", lambda request, plan=None: "[HERMES PLAN]\n- intent: general_chat")
    monkeypatch.setattr(sloane_runtime, "remember_operator_action", lambda action, details=None, limit=40: None)

    res = sloane_runtime.generate_sloane_response(
        base_persona="System",
        chat_history=[{"role": "user", "content": "Hello"}],
        grounding_block="",
        target_name="Sloane",
    )
    assert res["provider"] == "ollama"
    assert res["fallback_reason"] == "hermes down"


def test_runtime_includes_hermes_grounding(monkeypatch):
    from tools import sloane_runtime

    captured = {}

    monkeypatch.setattr(
        sloane_runtime,
        "load_runtime_config",
        lambda: {
            "runtime": {
                "default_provider": "ollama",
                "fallback_provider": "ollama",
                "providers": {
                    "ollama": {"enabled": True, "model": "qwen"},
                    "hermes_api": {"enabled": False, "base_url": "http://127.0.0.1:8000", "model": "hermes"},
                },
            }
        },
    )
    monkeypatch.setattr(sloane_runtime, "get_runtime_status", lambda: {"providers": {"hermes_api": {"online": False}}, "active_provider": "ollama"})
    monkeypatch.setattr(sloane_runtime, "build_hermes_grounding", lambda user_text: "[HERMES SKILLS]\n- Telemetry Observatory")
    monkeypatch.setattr(
        sloane_runtime,
        "plan_operator_mission",
        lambda request, context=None: {"intent": "general_chat", "requested_by": "Rob", "plan_steps": []},
    )
    monkeypatch.setattr(sloane_runtime, "build_operator_grounding", lambda request, plan=None: "[HERMES PLAN]\n- intent: general_chat")
    monkeypatch.setattr(sloane_runtime, "remember_operator_action", lambda action, details=None, limit=40: None)

    def fake_ollama(prompt, cfg):
        captured["prompt"] = prompt
        return {"provider": "ollama", "model": "qwen", "text": "Fallback reply"}

    monkeypatch.setattr(sloane_runtime, "_generate_with_ollama", fake_ollama)

    sloane_runtime.generate_sloane_response(
        base_persona="System",
        chat_history=[{"role": "user", "content": "Show telemetry"}],
        grounding_block="[BASE]",
        target_name="Sloane",
    )

    assert "[HERMES SKILLS]" in captured["prompt"]


def test_generate_with_hermes_api_uses_inline_api_key(monkeypatch):
    from tools import sloane_runtime

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Hermes is connected to Ollama."
                        }
                    }
                ]
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(sloane_runtime.requests, "post", fake_post)

    result = sloane_runtime._generate_with_hermes_api(
        [{"role": "user", "content": "hi"}],
        {
            "base_url": "http://127.0.0.1:8642",
            "model": "hermes-agent",
            "api_key": "xlink-local-key",
            "temperature": 0.1,
            "timeout_seconds": 42,
        },
    )

    assert captured["url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer xlink-local-key"
    assert captured["json"]["model"] == "hermes-agent"
    assert captured["json"]["temperature"] == 0.1
    assert captured["timeout"] == 42
    assert result["provider"] == "hermes_api"
    assert result["model"] == "hermes-agent"
    assert result["text"] == "Hermes is connected to Ollama."
