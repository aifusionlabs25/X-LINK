"""
X-LINK HUB v3 — Smoke Test Suite
Validates core contracts: router resolution, menu loading, tool contracts, status registry.
Run: python -m pytest tests/test_hub_smoke.py -v
"""

import os
import sys
import asyncio
import json
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


# ── 1. Router resolves all 5 tools ────────────────────────────

EXPECTED_TOOLS = [
    ("direct_line", "DirectLineTool"),
    ("usage_auditor", "UsageAuditorTool"),
    ("xagent_eval", "XAgentEvalTool"),
    ("briefing", "BriefingTool"),
]


@pytest.mark.parametrize("tool_key,expected_class", EXPECTED_TOOLS)
def test_router_resolves_tool(tool_key, expected_class):
    """Router must dynamically resolve each registered tool."""
    from hub.router import resolve_tool
    tool = resolve_tool(tool_key)
    assert tool is not None, f"Router failed to resolve '{tool_key}'"
    assert tool.__class__.__name__ == expected_class
    assert tool.key == tool_key


def test_router_rejects_unknown_tool():
    """Router must return None for unregistered keys."""
    from hub.router import resolve_tool
    assert resolve_tool("nonexistent_tool") is None


# ── 2. Menu loads from YAML ───────────────────────────────────

def test_menu_loads():
    """hub_menu.yaml must parse and return sections."""
    from hub.menu_state import get_sections
    sections = get_sections()
    assert isinstance(sections, list)
    assert len(sections) == 4
    keys = [s["key"] for s in sections]
    assert keys == ["primary", "reports", "system", "advanced"]


def test_menu_has_all_items():
    """Menu must contain all expected items."""
    from hub.menu_state import get_sections
    all_items = []
    for section in get_sections():
        for item in section.get("items", []):
            all_items.append(item["key"])
    assert "direct_line" in all_items
    assert "usage_auditor" in all_items
    assert "xagent_eval" in all_items
    assert "briefing" in all_items
    assert "sync_status" in all_items
    assert "bridge_status" in all_items
    assert "scout_workers" in all_items


def test_menu_tool_keys():
    """get_tool_keys() must return only tool-type items."""
    from hub.menu_state import get_tool_keys
    keys = get_tool_keys()
    assert set(keys) == {"direct_line", "usage_auditor", "xagent_eval"}


# ── 3. Each tool returns structured result contract ───────────

@pytest.mark.parametrize("tool_key", [
    "direct_line", "usage_auditor", "xagent_eval", "briefing",
])
def test_tool_result_contract(tool_key):
    """Each tool must return a ToolResult with required fields when run."""
    from hub.router import resolve_tool
    tool = resolve_tool(tool_key)
    assert tool is not None

    # Run with empty/minimal inputs — should either succeed or fail gracefully
    context = {"config_dir": os.path.join(ROOT_DIR, "config"), "vault_dir": os.path.join(ROOT_DIR, "vault")}

    # Pick inputs that won't require external services
    if tool_key == "xagent_eval":
        inputs = {"target_agent": "test_agent"}
    elif tool_key == "direct_line":
        inputs = {}  # Will fail gracefully (no message)
    else:
        inputs = {}

    result = asyncio.run(tool.run(context, inputs))

    # Contract checks
    assert hasattr(result, "tool_key")
    assert hasattr(result, "run_id")
    assert hasattr(result, "status")
    assert hasattr(result, "data")
    assert hasattr(result, "artifacts")
    assert hasattr(result, "errors")
    assert hasattr(result, "summary")
    assert result.status in ("success", "error", "pending", "running")

    # Serializable
    d = result.to_dict()
    assert isinstance(d, dict)
    json.dumps(d)  # Must not raise


def test_sloane_runtime_status_surface():
    from tools.sloane_runtime import get_runtime_status

    status = get_runtime_status()
    assert "default_provider" in status
    assert "active_provider" in status
    assert "providers" in status
    assert "ollama" in status["providers"]


def test_tool_registry_describes_hermes_console():
    import yaml

    path = os.path.join(ROOT_DIR, "config", "tool_registry.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["tools"]["direct_line"]["description"] == "Freeform conversational command lane to Hermes"


def test_mel_pending_summary_builder_surfaces_best_artifacts():
    from tools.synapse_bridge import _summarize_pending_payload

    payload = {
        "pending_id": "amy_20260412_081030",
        "agent_slug": "amy",
        "created_at": "2026-04-12T08:10:30.734943",
        "snapshot_path": "C:\\repo\\vault\\mel\\history\\amy_snapshot.txt",
        "diagnostic": {
            "failure_category": "flow_naturalness",
            "failed_exchange": "Weakest category: flow_naturalness",
        },
        "baseline": {
            "batch_id": "mel_e60a48b6",
            "score": 63.4,
            "pass_rate": 0.0,
            "verdict": "NO_SHIP",
        },
        "challengers": [
            {
                "variant": "proof_pressure_mode",
                "result": {
                    "batch_id": "mel_169b74ce",
                    "score": 61.8,
                },
            }
        ],
        "recommendation": {
            "variant": "baseline",
            "score": 63.4,
            "improvement": -1.6,
            "passes_threshold": False,
            "rationale": "Baseline outperformed all challengers.",
        },
    }

    summary = _summarize_pending_payload(payload, latest_log_path="C:\\repo\\vault\\mel\\logs\\session.log")

    assert summary["available"] is True
    assert summary["agent_slug"] == "amy"
    assert summary["best_variant"] == "baseline"
    assert summary["artifacts"]["pending_path"].endswith("amy_20260412_081030.json")
    assert summary["artifacts"]["snapshot_path"].endswith("amy_snapshot.txt")
    assert summary["artifacts"]["latest_log_path"].endswith("session.log")


def test_mel_pending_summary_builder_uses_recommended_challenger_batch():
    from tools.synapse_bridge import _summarize_pending_payload

    payload = {
        "pending_id": "amy_test",
        "agent_slug": "amy",
        "baseline": {
            "batch_id": "mel_base",
            "score": 70.0,
            "pass_rate": 0.0,
            "verdict": "NO_SHIP",
        },
        "challengers": [
            {
                "variant": "proof_pressure_mode",
                "result": {
                    "batch_id": "mel_best",
                    "score": 73.3,
                },
            }
        ],
        "recommendation": {
            "variant": "proof_pressure_mode",
            "score": 73.3,
            "improvement": 3.3,
            "passes_threshold": False,
        },
    }

    summary = _summarize_pending_payload(payload)

    assert summary["best_variant"] == "proof_pressure_mode"
    assert summary["best_score"] == 73.3
    assert summary["artifacts"]["recommended_batch_summary_path"] in {"", os.path.join(ROOT_DIR, "vault", "evals", "batches", "mel_best", "batch_summary.json")}


# ── 4. Status registry loads cleanly ──────────────────────────

def test_status_registry_loads():
    """StatusRegistry must instantiate and return a dict."""
    from hub.status_registry import get_status
    status = get_status()
    assert isinstance(status, dict)
    assert "bridge" in status
    assert "sync" in status
    assert "connected" in status["bridge"]
    assert "last_run_at" in status["sync"]


def test_status_registry_bridge_fields():
    """Bridge status must include expected fields."""
    from hub.status_registry import get_status
    bridge = get_status()["bridge"]
    assert "connected" in bridge
    assert "cdp_url" in bridge
    assert "active_tabs" in bridge


# ── 5. Config files parse ─────────────────────────────────────

def test_reveal_hub_identifies_startup_leftovers():
    from tools.reveal_hub_safe import is_startup_leftover_url

    assert is_startup_leftover_url("about:blank") is True
    assert is_startup_leftover_url("chrome-error://chromewebdata/") is True
    assert is_startup_leftover_url("chrome://newtab/") is True
    assert is_startup_leftover_url("http://localhost:5001/hub/index.html") is False


def test_reveal_hub_default_url_forces_clean_home():
    from tools.reveal_hub_safe import DEFAULT_HUB_URL

    assert "startup_home=1" in DEFAULT_HUB_URL


def test_tool_registry_parses():
    """tool_registry.yaml must parse and contain expected tools."""
    import yaml
    path = os.path.join(ROOT_DIR, "config", "tool_registry.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tools = data.get("tools", {})
    assert "direct_line" in tools
    assert "usage_auditor" in tools
    assert "xagent_eval" in tools
    assert "briefing" in tools


def test_scoring_rubrics_parses():
    """scoring_rubrics.yaml must parse and contain default_v1 rubric."""
    import yaml
    path = os.path.join(ROOT_DIR, "config", "scoring_rubrics.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "default_v1" in data
    assert "categories" in data["default_v1"]
    assert len(data["default_v1"]["categories"]) == 9
