import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def _timestamp() -> str:
    return datetime.now().isoformat()


def default_watch_patterns(kind: str) -> List[Dict[str, Any]]:
    key = str(kind or "").strip().lower()
    if key == "eval":
        return [
            {"key": "dispatch", "label": "Dispatch Started", "pattern": r"\b(starting|initiated|preparing run)\b", "severity": "info"},
            {"key": "run_active", "label": "Run Active", "pattern": r"\b(simulating run|capturing run|completed run)\b", "severity": "info"},
            {"key": "review_active", "label": "Reviewer Active", "pattern": r"\b(reviewer|review team|apex)\b", "severity": "info"},
            {"key": "report_ready", "label": "Report Ready", "pattern": r"\b(report|packet|summary)\b", "severity": "info"},
            {"key": "completed", "label": "Mission Completed", "pattern": r"\b(completed|complete|success)\b", "severity": "success"},
            {"key": "failed", "label": "Mission Failed", "pattern": r"\b(failed|error|aborted|mismatch)\b", "severity": "error"},
        ]
    if key == "archive":
        return [
            {"key": "dispatch", "label": "Archive Dispatched", "pattern": r"\b(targeting|archive sweep launched|connecting)\b", "severity": "info"},
            {"key": "approval", "label": "Founder Action Required", "pattern": r"\b(waiting for founder|confirmation required|resume archive|intervention)\b", "severity": "warning"},
            {"key": "platform_scan", "label": "Platform Scan", "pattern": r"\b(scanning|history scan|history item)\b", "severity": "info"},
            {"key": "file_saved", "label": "Archive Saved", "pattern": r"\bsaved\b", "severity": "success"},
            {"key": "summary_ready", "label": "Summary Ready", "pattern": r"\bsummary written|synthesis\b", "severity": "success"},
            {"key": "completed", "label": "Archive Completed", "pattern": r"\barchive intel sweep completed|completed\b", "severity": "success"},
            {"key": "failed", "label": "Archive Failed", "pattern": r"\b(error|failed|aborted|did not save|did not yield|diagnostics)\b", "severity": "error"},
        ]
    return [
        {"key": "completed", "label": "Completed", "pattern": r"\b(completed|success)\b", "severity": "success"},
        {"key": "failed", "label": "Failed", "pattern": r"\b(error|failed|aborted)\b", "severity": "error"},
    ]


def _event_message(event: Dict[str, Any]) -> str:
    parts = [
        str(event.get("status") or "").strip(),
        str(event.get("phase") or "").strip(),
        str(event.get("detail") or "").strip(),
        str(event.get("step") or "").strip(),
    ]
    return " ".join(part for part in parts if part).strip()


def _match_signals(message: str, patterns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lowered = str(message or "").strip().lower()
    matches: List[Dict[str, Any]] = []
    if not lowered:
        return matches
    for pattern in patterns or []:
        expr = str(pattern.get("pattern") or "").strip()
        if not expr:
            continue
        try:
            if re.search(expr, lowered, flags=re.IGNORECASE):
                matches.append(
                    {
                        "key": pattern.get("key"),
                        "label": pattern.get("label") or pattern.get("key"),
                        "severity": pattern.get("severity") or "info",
                    }
                )
        except re.error:
            continue
    return matches


def append_watched_event(
    state: Dict[str, Any],
    *,
    kind: str,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    detail: Optional[str] = None,
    step: Optional[str] = None,
    percent: Optional[int] = None,
    source: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    limit: int = 80,
) -> Dict[str, Any]:
    payload = dict(state or {})
    patterns = payload.get("watch_patterns") or default_watch_patterns(kind)
    payload["watch_patterns"] = patterns

    event = {
        "timestamp": _timestamp(),
        "kind": kind,
        "status": status,
        "phase": phase,
        "detail": detail,
        "step": step,
        "percent": percent,
        "source": source or kind,
    }
    if extra:
        event.update(extra)

    signature = {
        "status": event.get("status"),
        "phase": event.get("phase"),
        "detail": event.get("detail"),
        "step": event.get("step"),
        "percent": event.get("percent"),
    }
    events = list(payload.get("events") or [])
    last = events[-1] if events else None
    if not last or any(last.get(key) != value for key, value in signature.items()):
        event["matched_signals"] = _match_signals(_event_message(event), patterns)
        events.append(event)
        payload["events"] = events[-max(1, limit) :]

        known = list(payload.get("matched_signals") or [])
        seen = {(str(item.get("key")), str(item.get("severity"))) for item in known}
        for signal in event["matched_signals"]:
            marker = (str(signal.get("key")), str(signal.get("severity")))
            if marker not in seen:
                known.append(signal)
                seen.add(marker)
        payload["matched_signals"] = known
        if event["matched_signals"]:
            payload["latest_signal"] = event["matched_signals"][-1]
    return payload
