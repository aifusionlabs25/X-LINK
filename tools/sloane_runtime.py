import os
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

from tools.hermes_memory import build_hermes_grounding, remember_operator_action
from tools.hermes_operator import build_operator_grounding, plan_operator_mission
from tools.telemetry import (
    capture_gpu_sample,
    estimate_tokens_from_messages,
    estimate_tokens_from_text,
    record_llm_call,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "sloane_runtime.yaml"


def load_runtime_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {
            "runtime": {
                "default_provider": "ollama",
                "fallback_provider": "ollama",
                "providers": {
                    "ollama": {
                        "enabled": True,
                        "model": "qwen2.5:14b-instruct-q6_K",
                        "endpoint": "http://127.0.0.1:11434/api/generate",
                        "timeout_seconds": 600,
                        "temperature": 0.5,
                        "stop": ["Rob:", "###"],
                    }
                },
            }
        }
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _provider_cfg(name: str) -> Dict[str, Any]:
    runtime = load_runtime_config().get("runtime", {})
    return runtime.get("providers", {}).get(name, {})


def _runtime_cfg() -> Dict[str, Any]:
    return load_runtime_config().get("runtime", {})


def _safe_get_json(url: str, timeout: int = 3, headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    try:
        res = requests.get(url, timeout=timeout, headers=headers)
        if res.status_code != 200:
            return None
        return res.json()
    except Exception:
        return None


def get_runtime_status() -> Dict[str, Any]:
    runtime = _runtime_cfg()
    default_provider = runtime.get("default_provider", "ollama")
    fallback_provider = runtime.get("fallback_provider", "ollama")
    providers = runtime.get("providers", {})

    status: Dict[str, Any] = {
        "default_provider": default_provider,
        "fallback_provider": fallback_provider,
        "active_provider": "ollama",
        "providers": {},
    }

    hermes_cfg = providers.get("hermes_api", {})
    hermes_enabled = bool(hermes_cfg.get("enabled"))
    hermes_base = str(hermes_cfg.get("base_url") or "").rstrip("/")
    hermes_health = None
    hermes_headers: Dict[str, str] = {}
    hermes_api_key = str(hermes_cfg.get("api_key") or "").strip()
    if not hermes_api_key:
        hermes_api_key_env = hermes_cfg.get("api_key_env")
        if hermes_api_key_env:
            hermes_api_key = str(os.getenv(str(hermes_api_key_env), "")).strip()
    if hermes_api_key:
        hermes_headers["Authorization"] = f"Bearer {hermes_api_key}"
    if hermes_enabled and hermes_base:
        hermes_health = _safe_get_json(
            f"{hermes_base}/v1/models",
            timeout=3,
            headers=hermes_headers or None,
        )
    hermes_online = bool(hermes_health)
    status["providers"]["hermes_api"] = {
        "enabled": hermes_enabled,
        "online": hermes_online,
        "base_url": hermes_base,
        "model": hermes_cfg.get("model"),
    }

    ollama_cfg = providers.get("ollama", {})
    ollama_health = _safe_get_json("http://127.0.0.1:11434/api/version", timeout=2)
    ollama_online = bool(ollama_health)
    status["providers"]["ollama"] = {
        "enabled": bool(ollama_cfg.get("enabled", True)),
        "online": ollama_online,
        "endpoint": ollama_cfg.get("endpoint"),
        "model": ollama_cfg.get("model"),
    }

    if default_provider in {"auto", "hermes_api"} and hermes_enabled and hermes_online:
        status["active_provider"] = "hermes_api"
    elif default_provider == "ollama":
        status["active_provider"] = "ollama"
    elif fallback_provider == "ollama":
        status["active_provider"] = "ollama"

    return status


def _messages_from_prompt(base_persona: str, chat_history: List[Dict[str, str]], grounding_block: str, target_name: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [{"role": "system", "content": f"{base_persona}\n{grounding_block}".strip()}]
    for msg in chat_history:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant" and target_name and target_name != "Sloane":
            content = content.replace("Sloane", target_name)
        messages.append({"role": role, "content": content})
    return messages


def _generate_with_ollama(prompt: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    started_at = datetime.now()
    response = requests.post(
        cfg.get("endpoint", "http://127.0.0.1:11434/api/generate"),
        json={
            "model": cfg.get("model", "qwen2.5:14b-instruct-q6_K"),
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": cfg.get("temperature", 0.5),
                "stop": cfg.get("stop", ["Rob:", "###"]),
            },
        },
        timeout=int(cfg.get("timeout_seconds", 600)),
    )
    response.raise_for_status()
    payload = response.json()
    result = {
        "provider": "ollama",
        "model": cfg.get("model", "qwen2.5:14b-instruct-q6_K"),
        "text": (payload.get("response") or "").strip(),
    }
    ended_at = datetime.now()
    record_llm_call(
        workflow="hermes_runtime",
        provider="ollama",
        model=result["model"],
        started_at=started_at,
        ended_at=ended_at,
        input_tokens_est=estimate_tokens_from_text(prompt),
        output_tokens_est=estimate_tokens_from_text(result["text"]),
        success=True,
        metadata={"target": "hermes"},
    )
    capture_gpu_sample(workflow="hermes_runtime", metadata={"provider": "ollama", "model": result["model"]})
    return result


def _generate_with_hermes_api(messages: List[Dict[str, str]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    base_url = str(cfg.get("base_url") or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        api_key_env = cfg.get("api_key_env")
        if api_key_env:
            api_key = str(os.getenv(str(api_key_env), "")).strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    started_at = datetime.now()
    response = requests.post(
        f"{base_url}/v1/chat/completions",
        headers=headers,
        json={
            "model": cfg.get("model", "hermes-agent"),
            "messages": messages,
            "temperature": cfg.get("temperature", 0.3),
        },
        timeout=int(cfg.get("timeout_seconds", 180)),
    )
    response.raise_for_status()
    payload = response.json()
    text = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    result = {
        "provider": "hermes_api",
        "model": cfg.get("model", "hermes-agent"),
        "text": text,
    }
    ended_at = datetime.now()
    record_llm_call(
        workflow="hermes_runtime",
        provider="hermes_api",
        model=result["model"],
        started_at=started_at,
        ended_at=ended_at,
        input_tokens_est=estimate_tokens_from_messages(messages),
        output_tokens_est=estimate_tokens_from_text(text),
        success=True,
        metadata={"target": "hermes"},
    )
    capture_gpu_sample(workflow="hermes_runtime", metadata={"provider": "hermes_api", "model": result["model"]})
    return result


def generate_sloane_response(
    *,
    base_persona: str,
    chat_history: List[Dict[str, str]],
    grounding_block: str,
    target_name: str = "Sloane",
) -> Dict[str, Any]:
    runtime = _runtime_cfg()
    default_provider = runtime.get("default_provider", "ollama")
    fallback_provider = runtime.get("fallback_provider", "ollama")
    status = get_runtime_status()
    latest_user_text = next((str(msg.get("content") or "") for msg in reversed(chat_history) if msg.get("role") == "user"), "")
    operator_plan = plan_operator_mission(
        latest_user_text,
        {
            "requested_by": "Rob",
            "persona": target_name.lower(),
            "target_agent": target_name.lower(),
            "chat_history": chat_history,
            "source": "sloane_runtime",
        },
    )
    hermes_grounding = build_hermes_grounding(latest_user_text)
    operator_grounding = build_operator_grounding(latest_user_text, operator_plan)
    combined_grounding = "\n\n".join(
        block for block in [grounding_block, hermes_grounding, operator_grounding] if block.strip()
    )
    messages = _messages_from_prompt(base_persona, chat_history, combined_grounding, target_name)

    prompt = f"{base_persona}\n[CONVERSATION]\n"
    for msg in chat_history:
        role = "Rob" if msg["role"] == "user" else target_name
        prompt += f"{role}: {msg['content']}\n"
    prompt += f"{combined_grounding}{target_name}:"

    if default_provider in {"auto", "hermes_api"} and status["providers"].get("hermes_api", {}).get("online"):
        try:
            result = _generate_with_hermes_api(messages, _provider_cfg("hermes_api"))
            result["orchestrator"] = "hermes_core"
            result["mission_plan"] = operator_plan
            remember_operator_action(
                "render_operator_reply",
                {
                    "provider": result.get("provider"),
                    "intent": operator_plan.get("intent"),
                    "target_name": target_name,
                },
            )
            return result
        except Exception as exc:
            if fallback_provider != "ollama":
                raise
            fallback = _generate_with_ollama(prompt, _provider_cfg("ollama"))
            fallback["fallback_reason"] = str(exc)
            fallback["orchestrator"] = "hermes_core"
            fallback["mission_plan"] = operator_plan
            remember_operator_action(
                "render_operator_reply_fallback",
                {
                    "provider": fallback.get("provider"),
                    "intent": operator_plan.get("intent"),
                    "target_name": target_name,
                    "reason": str(exc),
                },
            )
            return fallback

    result = _generate_with_ollama(prompt, _provider_cfg("ollama"))
    result["orchestrator"] = "hermes_core"
    result["mission_plan"] = operator_plan
    remember_operator_action(
        "render_operator_reply",
        {
            "provider": result.get("provider"),
            "intent": operator_plan.get("intent"),
            "target_name": target_name,
        },
    )
    return result


def generate_hermes_response(
    *,
    base_persona: str,
    chat_history: List[Dict[str, str]],
    grounding_block: str,
    target_name: str = "Hermes",
) -> Dict[str, Any]:
    return generate_sloane_response(
        base_persona=base_persona,
        chat_history=chat_history,
        grounding_block=grounding_block,
        target_name=target_name,
    )
