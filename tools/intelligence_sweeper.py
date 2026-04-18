"""
Retired legacy Scout entrypoint.

This file remains only as a guardrail so stale scripts fail closed with a
clear message.
"""

from __future__ import annotations

import sys

MESSAGE = (
    "The legacy intelligence_sweeper.py flow was retired. "
    "Use tools/research_scout.py for live research workflows instead."
)


def main() -> int:
    print(MESSAGE)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
