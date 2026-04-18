import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from tools.hermes_memory import HERMES_DIR, record_lesson

PENDING_DIR = ROOT_DIR / "vault" / "mel" / "pending"
BATCHES_DIR = ROOT_DIR / "vault" / "evals" / "batches"
REPORTS_DIR = HERMES_DIR / "reports"


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_batch_summary(batch_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not batch_id:
        return None
    return _load_json(BATCHES_DIR / batch_id / "batch_summary.json")


def _batch_summary_path(batch_id: Optional[str]) -> Optional[str]:
    if not batch_id:
        return None
    path = BATCHES_DIR / batch_id / "batch_summary.json"
    return str(path) if path.exists() else None


def _top_warning_phrase(batch_summary: Optional[Dict[str, Any]]) -> Optional[str]:
    if not batch_summary:
        return None
    warning_counter: Counter[str] = Counter()
    for run in batch_summary.get("runs", []) or []:
        for warning in run.get("warnings", []) or []:
            cleaned = str(warning).strip()
            if cleaned:
                warning_counter[cleaned] += 1
    if not warning_counter:
        return None
    return warning_counter.most_common(1)[0][0]


def _top_fail_flag_note(batch_summary: Optional[Dict[str, Any]], category_key: str) -> Optional[str]:
    if not batch_summary:
        return None
    notes: Counter[str] = Counter()
    for run in batch_summary.get("runs", []) or []:
        for category in run.get("categories", []) or []:
            if category.get("key") == category_key and category.get("fail_flag"):
                note = str(category.get("notes", "")).strip()
                if note:
                    notes[note] += 1
    if not notes:
        return None
    return notes.most_common(1)[0][0]


def _build_pending_lesson(payload: Dict[str, Any], path: Path) -> Dict[str, Any]:
    agent = str(payload.get("agent_slug", "agent"))
    pending_id = str(payload.get("pending_id", path.stem))
    status = str(payload.get("status", "pending"))
    diagnostic = payload.get("diagnostic", {}) or {}
    baseline = payload.get("baseline", {}) or {}
    recommendation = payload.get("recommendation", {}) or {}
    failure_category = str(diagnostic.get("failure_category", "general_performance"))
    baseline_score = float(baseline.get("score", 0) or 0)
    best_score = float(recommendation.get("score", baseline_score) or baseline_score)
    improvement = float(recommendation.get("improvement", round(best_score - baseline_score, 1)) or 0)
    variant = str(recommendation.get("variant", "unknown"))
    summary = (
        f"{agent} MEL review {pending_id} ended {status}. "
        f"Primary blocker was {failure_category}. Baseline scored {baseline_score:.1f}, "
        f"recommended {variant} challenger reached {best_score:.1f}, improvement {improvement:+.1f}."
    )
    if status == "rejected" and improvement > 0:
        summary += " Human review still rejected the patch, so score lift alone was not trusted."
    if status == "approved":
        summary += " Human approval indicates the patch was considered worth adopting."
    evidence_paths = [str(path)]
    baseline_batch_path = _batch_summary_path(payload.get("baseline", {}).get("batch_id"))
    if baseline_batch_path:
        evidence_paths.append(baseline_batch_path)
    return {
        "source": "mel_backlog",
        "title": f"{agent} backlog review {pending_id}",
        "summary": summary,
        "tags": ["mel", "backlog", agent, status, failure_category],
        "confidence": 0.82 if status in {"approved", "rejected"} else 0.68,
        "evidence_paths": evidence_paths,
        "dedupe_key": f"backlog:{pending_id}",
    }


def _build_agent_pattern_lessons(agent: str, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    failure_counts: Counter[str] = Counter()
    rejected_positive = 0
    statuses: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    note_counter: Counter[str] = Counter()
    evidence_paths: List[str] = []

    for entry in entries:
        payload = entry["payload"]
        path = entry["path"]
        diagnostic = payload.get("diagnostic", {}) or {}
        recommendation = payload.get("recommendation", {}) or {}
        batch_id = None
        if isinstance(recommendation.get("result"), dict):
            batch_id = recommendation["result"].get("batch_id")
        if not batch_id:
            batch_id = payload.get("baseline", {}).get("batch_id")
        batch_summary = _load_batch_summary(batch_id)

        failure_category = str(diagnostic.get("failure_category", "general_performance"))
        failure_counts[failure_category] += 1
        statuses[str(payload.get("status", "pending"))] += 1
        if str(payload.get("status")) == "rejected" and float(recommendation.get("improvement", 0) or 0) > 0:
            rejected_positive += 1
        warning = _top_warning_phrase(batch_summary)
        if warning:
            warning_counter[warning] += 1
        fail_note = _top_fail_flag_note(batch_summary, failure_category)
        if fail_note:
            note_counter[fail_note] += 1
        evidence_paths.append(str(path))

    top_category = failure_counts.most_common(1)[0][0] if failure_counts else "general_performance"
    lessons: List[Dict[str, Any]] = []

    summary = (
        f"Historical MEL backlog for {agent} most often failed on {top_category} "
        f"across {failure_counts[top_category]} recorded review cycles."
    )
    if note_counter:
        summary += f" Common failure note: {note_counter.most_common(1)[0][0]}"
    elif warning_counter:
        summary += f" Common warning: {warning_counter.most_common(1)[0][0]}"
    lessons.append(
        {
            "source": "mel_backlog_pattern",
            "title": f"{agent} recurring MEL blocker",
            "summary": summary,
            "tags": ["mel", "backlog", agent, top_category],
            "confidence": 0.86,
            "evidence_paths": evidence_paths[:5],
            "dedupe_key": f"backlog-pattern:{agent}:primary",
        }
    )

    if rejected_positive:
        lessons.append(
            {
                "source": "mel_backlog_pattern",
                "title": f"{agent} score-lift caution",
                "summary": (
                    f"{agent} had {rejected_positive} historical MEL cycles where score improved but the patch was still rejected. "
                    "Treat raw score lift as insufficient when naturalness, truthfulness, or role fit still look wrong to a human reviewer."
                ),
                "tags": ["mel", "backlog", agent, "false_positive_risk"],
                "confidence": 0.88,
                "evidence_paths": evidence_paths[:5],
                "dedupe_key": f"backlog-pattern:{agent}:score-lift-caution",
            }
        )

    if statuses.get("approved"):
        lessons.append(
            {
                "source": "mel_backlog_pattern",
                "title": f"{agent} approved-patch evidence exists",
                "summary": (
                    f"{agent} has {statuses['approved']} historically approved MEL outcomes in the backlog. "
                    "Use those as stronger evidence than unaudited challenger suggestions when comparing future recommendations."
                ),
                "tags": ["mel", "backlog", agent, "approved_history"],
                "confidence": 0.8,
                "evidence_paths": evidence_paths[:5],
                "dedupe_key": f"backlog-pattern:{agent}:approved-history",
            }
        )

    return lessons


def mine_historical_mel_backlog(limit: Optional[int] = None) -> Dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pending_paths = sorted(PENDING_DIR.glob("*.json"))
    if limit is not None and limit >= 0:
        pending_paths = pending_paths[-limit:]

    pending_payloads: List[Dict[str, Any]] = []
    created = 0
    reused = 0

    for path in pending_paths:
        payload = _load_json(path)
        if not payload or not payload.get("agent_slug"):
            continue
        pending_payloads.append({"path": path, "payload": payload})
        result = record_lesson(**_build_pending_lesson(payload, path))
        if result.get("_existing"):
            reused += 1
        else:
            created += 1

    by_agent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in pending_payloads:
        by_agent[str(entry["payload"].get("agent_slug"))].append(entry)

    pattern_created = 0
    pattern_reused = 0
    for agent, entries in by_agent.items():
        for lesson in _build_agent_pattern_lessons(agent, entries):
            result = record_lesson(**lesson)
            if result.get("_existing"):
                pattern_reused += 1
            else:
                pattern_created += 1

    report = {
        "timestamp": datetime.now().isoformat(),
        "pending_files_scanned": len(pending_payloads),
        "agents_mined": sorted(by_agent.keys()),
        "agent_counts": {agent: len(entries) for agent, entries in by_agent.items()},
        "individual_lessons_created": created,
        "individual_lessons_reused": reused,
        "pattern_lessons_created": pattern_created,
        "pattern_lessons_reused": pattern_reused,
        "report_path": "",
    }
    report_path = REPORTS_DIR / f"backlog_mining_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mine historical MEL backlog into Hermes lessons.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of pending files to scan.")
    args = parser.parse_args()
    result = mine_historical_mel_backlog(limit=args.limit)
    print(json.dumps(result, indent=2))
