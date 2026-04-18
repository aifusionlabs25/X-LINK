"""
Legacy Intel Scout compatibility helpers.

This module remains only to return a clear retired status if a stale import
still calls it.
"""


async def run_synthesis(source: str = "legacy", query: str = "") -> dict:
    return {
        "status": "retired",
        "source": source,
        "query": query,
        "message": "The legacy Intel Scout synthesis flow was retired. Use research_scout.py for live research workflows.",
    }
