"""
X-LINK HUB v3 — Command Schema
Pydantic-based schemas for tool commands and results.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCommand:
    """Normalized command passed to the router."""
    tool_key: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    context_overrides: Dict[str, Any] = field(default_factory=dict)
    run_id: Optional[str] = None


@dataclass
class ArtifactManifest:
    """Describes a saved artifact."""
    path: str
    type: str          # json, markdown, screenshot, transcript, scorecard
    tool_key: str
    run_id: str
    timestamp: str = ""


@dataclass
class RouterResult:
    """Structured response from the router after tool execution."""
    tool_key: str
    run_id: str
    status: str                          # success | error
    summary: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[ArtifactManifest] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
