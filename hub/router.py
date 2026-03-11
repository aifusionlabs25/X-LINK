"""
X-LINK HUB v3 — Central Command Router

Accepts a normalized command → resolves tool key → validates input →
instantiates tool → passes shared runtime context → collects result →
stores artifacts → returns structured summary.

RULE: Zero tool-specific branching logic lives here.
"""

import os
import sys
import yaml
import logging
import importlib
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from hub.command_schema import ToolCommand, RouterResult
from tools.base_tool import BaseTool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("hub.router")

CONFIG_DIR = os.path.join(ROOT_DIR, "config")


def load_tool_registry() -> dict:
    """Load tool definitions from config/tool_registry.yaml."""
    path = os.path.join(CONFIG_DIR, "tool_registry.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("tools", {})


def resolve_tool(tool_key: str) -> Optional[BaseTool]:
    """
    Dynamically import and instantiate a tool by its registry key.
    Returns None if the tool is not found or fails to load.
    """
    registry = load_tool_registry()
    entry = registry.get(tool_key)
    if not entry:
        logger.error(f"[ROUTER] Tool key '{tool_key}' not found in registry.")
        return None

    module_path = entry["module"]
    class_name = entry["class"]

    try:
        module = importlib.import_module(module_path)
        tool_class = getattr(module, class_name)
        return tool_class()
    except Exception as e:
        logger.error(f"[ROUTER] Failed to load tool '{tool_key}': {e}")
        return None


def build_context(command: ToolCommand) -> dict:
    """
    Build the shared runtime context passed to every tool.
    This is where browser/CDP/Ollama connections would be injected.
    """
    context = {
        "root_dir": ROOT_DIR,
        "config_dir": CONFIG_DIR,
        "vault_dir": os.path.join(ROOT_DIR, "vault"),
        "run_id": command.run_id,
    }
    context.update(command.context_overrides)
    return context


async def route(command: ToolCommand) -> RouterResult:
    """
    Route a command to its tool, execute, and return structured results.
    """
    logger.info(f"[ROUTER] Routing command: {command.tool_key} (run: {command.run_id})")

    # 1. Resolve tool
    tool = resolve_tool(command.tool_key)
    if not tool:
        return RouterResult(
            tool_key=command.tool_key,
            run_id=command.run_id or "unknown",
            status="error",
            errors=[f"Tool '{command.tool_key}' could not be resolved."],
        )

    # 2. Build context
    context = build_context(command)

    # 3. Execute full lifecycle
    result = await tool.run(context, command.inputs)

    # 4. Package into RouterResult
    return RouterResult(
        tool_key=result.tool_key,
        run_id=result.run_id,
        status=result.status,
        summary=result.summary,
        data=result.data,
        errors=result.errors,
    )


# ── CLI Dry-Run ───────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    if len(sys.argv) < 2:
        print("Usage: python hub/router.py <tool_key> [--dry-run]")
        sys.exit(1)

    tool_key = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        tool = resolve_tool(tool_key)
        if tool:
            print(f"✅ Tool '{tool_key}' resolved: {tool.__class__.__name__}")
            print(f"   Key: {tool.key}")
            print(f"   Description: {tool.description}")
        else:
            print(f"❌ Tool '{tool_key}' could not be resolved.")
    else:
        cmd = ToolCommand(tool_key=tool_key, inputs={})
        result = asyncio.run(route(cmd))
        print(f"Result: {result.status} — {result.summary}")
        if result.errors:
            print(f"Errors: {result.errors}")
