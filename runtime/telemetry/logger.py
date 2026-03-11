"""
X-LINK HUB v3 — Runtime: Telemetry Logger
Shared operational logging for all tools.
"""

import os
import logging
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(ROOT_DIR, "vault", "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def get_ops_logger(name: str = "sloane_ops") -> logging.Logger:
    """Get the shared operational logger that writes to vault/logs/."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(
            os.path.join(LOG_DIR, f"{name}.log"), encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        logger.addHandler(fh)
    return logger


def log_tool_event(tool_key: str, run_id: str, event: str, data: dict = None):
    """Log a structured tool event to the ops log."""
    logger = get_ops_logger()
    msg = f"[{tool_key}:{run_id}] {event}"
    if data:
        msg += f" | {data}"
    logger.info(msg)
