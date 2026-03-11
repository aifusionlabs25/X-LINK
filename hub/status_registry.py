"""
X-LINK HUB v3 — Status Registry
Exposes system state as a queryable registry for the status layer.
Bridge/sync state lives here, not in the tool menu.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

logger = logging.getLogger("hub.status")


class StatusRegistry:
    """
    Centralized system status.
    UI reads from this; tools do not depend on it.
    """

    def __init__(self):
        self.bridge_connected: bool = False
        self.cdp_url: str = "http://127.0.0.1:9222"
        self.active_context_count: int = 0
        self.active_tab_count: int = 0
        self.sync_last_run_at: Optional[str] = None
        self.sync_last_result: Optional[str] = None
        self.sync_queue_depth: int = 0
        self.last_error: Optional[str] = None

    async def refresh_bridge_status(self):
        """Probe the CDP endpoint to determine bridge connectivity."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.cdp_url}/json/list", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.bridge_connected = True
                        self.active_tab_count = len(data)
                        self.active_context_count = 1
                        self.last_error = None
                    else:
                        self.bridge_connected = False
                        self.last_error = f"CDP returned {resp.status}"
        except Exception as e:
            self.bridge_connected = False
            self.last_error = str(e)

    def refresh_sync_status(self):
        """Check sync state from disk artifacts."""
        reports_dir = os.path.join(ROOT_DIR, "vault", "reports")
        if os.path.exists(reports_dir):
            files = sorted(os.listdir(reports_dir), reverse=True)
            audit_files = [f for f in files if f.startswith("audit_")]
            if audit_files:
                latest = audit_files[0]
                # Extract timestamp from filename or file mtime
                mtime = os.path.getmtime(os.path.join(reports_dir, latest))
                self.sync_last_run_at = datetime.fromtimestamp(mtime).isoformat()
                self.sync_last_result = "success"
            else:
                self.sync_last_result = "no_runs"

    def to_dict(self) -> dict:
        return {
            "bridge": {
                "connected": self.bridge_connected,
                "cdp_url": self.cdp_url,
                "active_contexts": self.active_context_count,
                "active_tabs": self.active_tab_count,
            },
            "sync": {
                "last_run_at": self.sync_last_run_at,
                "last_result": self.sync_last_result,
                "queue_depth": self.sync_queue_depth,
            },
            "last_error": self.last_error,
        }


# Singleton
_registry = StatusRegistry()


def get_status() -> dict:
    """Get the current system status as a dict."""
    _registry.refresh_sync_status()
    return _registry.to_dict()


async def get_full_status() -> dict:
    """Get full system status including async bridge probe."""
    await _registry.refresh_bridge_status()
    _registry.refresh_sync_status()
    return _registry.to_dict()
