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
    ("intelligence_scout", "IntelligenceScoutTool"),
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
    assert "intelligence_scout" in all_items
    assert "xagent_eval" in all_items
    assert "briefing" in all_items
    assert "sync_status" in all_items
    assert "bridge_status" in all_items
    assert "scout_workers" in all_items


def test_menu_tool_keys():
    """get_tool_keys() must return only tool-type items."""
    from hub.menu_state import get_tool_keys
    keys = get_tool_keys()
    assert set(keys) == {"direct_line", "usage_auditor", "intelligence_scout", "xagent_eval"}


# ── 3. Each tool returns structured result contract ───────────

@pytest.mark.parametrize("tool_key", [
    "direct_line", "usage_auditor", "intelligence_scout", "xagent_eval", "briefing",
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

def test_tool_registry_parses():
    """tool_registry.yaml must parse and contain expected tools."""
    import yaml
    path = os.path.join(ROOT_DIR, "config", "tool_registry.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tools = data.get("tools", {})
    assert "direct_line" in tools
    assert "usage_auditor" in tools
    assert "intelligence_scout" in tools
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
