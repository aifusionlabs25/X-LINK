import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
SKILLS_PATH = ROOT_DIR / "config" / "hermes_skills.yaml"
HERMES_DIR = ROOT_DIR / "vault" / "hermes"
LESSONS_PATH = HERMES_DIR / "lessons.jsonl"
OPERATIONAL_MEMORY_PATH = HERMES_DIR / "operational_memory.json"
TRUSTED_LESSON_SOURCES = {"ops"}


def ensure_hermes_dir() -> None:
    HERMES_DIR.mkdir(parents=True, exist_ok=True)


def load_skill_registry() -> List[Dict[str, Any]]:
    if not SKILLS_PATH.exists():
        return []
    with SKILLS_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [skill for skill in data.get("skills", []) if isinstance(skill, dict)]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default or {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default or {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_hermes_dir()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _normalize_path(path_str: str) -> str:
    try:
        return str(Path(path_str).resolve()).lower()
    except Exception:
        return str(path_str).lower()


def _is_trusted_evidence_path(path_str: str) -> bool:
    normalized = _normalize_path(path_str)
    root = str(ROOT_DIR.resolve()).lower()
    if not normalized.startswith(root):
        return False
    trusted_suffixes = (
        "\\vault\\mel\\pending\\",
        "\\vault\\evals\\batches\\",
        "\\vault\\evals\\runs\\",
        "\\vault\\mel\\checkpoints\\",
    )
    if any(segment in normalized for segment in ("\\vault\\mel\\logs\\", "session_")):
        return False
    if "\\vault\\mel\\pending\\" in normalized and normalized.endswith(".json"):
        return True
    if "\\vault\\evals\\batches\\" in normalized and normalized.endswith("\\batch_summary.json"):
        return True
    if "\\vault\\evals\\runs\\" in normalized and (
        normalized.endswith("\\transcript.txt") or normalized.endswith("\\scorecard.json")
    ):
        return True
    if "\\vault\\mel\\checkpoints\\" in normalized and normalized.endswith(".json"):
        return True
    return any(segment in normalized for segment in trusted_suffixes)


def _filter_trusted_evidence_paths(paths: Optional[List[str]]) -> List[str]:
    trusted: List[str] = []
    for path in paths or []:
        if path and _is_trusted_evidence_path(str(path)):
            trusted.append(str(path))
    return trusted


def lesson_is_trusted(lesson: Dict[str, Any]) -> bool:
    source = str(lesson.get("source", ""))
    trusted_paths = _filter_trusted_evidence_paths(lesson.get("evidence_paths", []))
    if trusted_paths:
        return True
    return source in TRUSTED_LESSON_SOURCES


def _default_operational_memory() -> Dict[str, Any]:
    return {
        "updated_at": None,
        "recent_missions": [],
        "recent_actions": [],
        "reusable_patterns": [],
        "rollback_checkpoints": [],
    }


def load_operational_memory() -> Dict[str, Any]:
    payload = _read_json(OPERATIONAL_MEMORY_PATH, _default_operational_memory())
    if not payload:
        payload = _default_operational_memory()
    for key, fallback in _default_operational_memory().items():
        payload.setdefault(key, fallback if not isinstance(fallback, list) else list(fallback))
    return payload


def save_operational_memory(payload: Dict[str, Any]) -> Dict[str, Any]:
    memory = _default_operational_memory()
    memory.update(payload or {})
    memory["updated_at"] = datetime.now().isoformat()
    _write_json(OPERATIONAL_MEMORY_PATH, memory)
    return memory


def remember_operator_action(action: str, details: Optional[Dict[str, Any]] = None, limit: int = 40) -> Dict[str, Any]:
    memory = load_operational_memory()
    actions = memory.setdefault("recent_actions", [])
    actions.append(
        {
            "timestamp": datetime.now().isoformat(),
            "action": str(action or "unknown"),
            "details": details or {},
        }
    )
    memory["recent_actions"] = actions[-max(1, limit) :]
    return save_operational_memory(memory)


def remember_mission_state(mission_state: Dict[str, Any], limit: int = 20) -> Dict[str, Any]:
    memory = load_operational_memory()
    recent = [item for item in memory.setdefault("recent_missions", []) if item.get("mission_id") != mission_state.get("mission_id")]
    recent.append(
        {
            "mission_id": mission_state.get("mission_id"),
            "owner_agent": mission_state.get("owner_agent"),
            "requested_by": mission_state.get("requested_by"),
            "intent": mission_state.get("intent"),
            "status": mission_state.get("status"),
            "active_step": mission_state.get("active_step"),
            "artifacts": mission_state.get("artifacts", {}),
            "updated_at": datetime.now().isoformat(),
        }
    )
    memory["recent_missions"] = recent[-max(1, limit) :]

    plan_steps = mission_state.get("plan_steps") or []
    pattern_key = f"{mission_state.get('intent', 'unknown')}::{len(plan_steps)}"
    patterns = memory.setdefault("reusable_patterns", [])
    existing = next((item for item in patterns if item.get("pattern_key") == pattern_key), None)
    if existing:
        existing["count"] = int(existing.get("count", 1)) + 1
        existing["last_seen_at"] = datetime.now().isoformat()
    else:
        patterns.append(
            {
                "pattern_key": pattern_key,
                "intent": mission_state.get("intent"),
                "step_count": len(plan_steps),
                "count": 1,
                "last_seen_at": datetime.now().isoformat(),
            }
        )
    memory["reusable_patterns"] = patterns[-max(1, limit) :]
    return save_operational_memory(memory)


def remember_rollback_checkpoint(checkpoint: Dict[str, Any], limit: int = 12) -> Dict[str, Any]:
    memory = load_operational_memory()
    checkpoints = memory.setdefault("rollback_checkpoints", [])
    checkpoints.append(
        {
            "timestamp": datetime.now().isoformat(),
            **(checkpoint or {}),
        }
    )
    memory["rollback_checkpoints"] = checkpoints[-max(1, limit) :]
    return save_operational_memory(memory)


def build_operational_memory_brief(user_text: str, mission_limit: int = 3, action_limit: int = 3) -> str:
    memory = load_operational_memory()
    text = (user_text or "").lower()
    blocks: List[str] = []

    missions = memory.get("recent_missions") or []
    mission_lines: List[str] = []
    for mission in reversed(missions[-mission_limit:]):
        intent = str(mission.get("intent", "unknown"))
        status = str(mission.get("status", "unknown"))
        if text and intent != "general_chat" and intent.replace("_", " ") not in text and len(mission_lines) >= 1:
            continue
        mission_lines.append(
            f"- {mission.get('mission_id', 'mission')}: {intent} | {status} | active step: {mission.get('active_step') or 'none'}"
        )
    if mission_lines:
        blocks.append("[HERMES OPERATIONS]\n" + "\n".join(mission_lines[:mission_limit]))

    action_lines = []
    for action in reversed((memory.get("recent_actions") or [])[-action_limit:]):
        action_lines.append(f"- {action.get('action', 'action')} at {action.get('timestamp', 'unknown time')}")
    if action_lines:
        blocks.append("[HERMES RECENT ACTIONS]\n" + "\n".join(action_lines))

    return "\n\n".join(blocks).strip()


def load_lessons(limit: int = 8, trusted_only: bool = True) -> List[Dict[str, Any]]:
    rows = _read_jsonl(LESSONS_PATH)
    if trusted_only:
        rows = [row for row in rows if lesson_is_trusted(row)]
    return rows[-limit:] if limit >= 0 else rows


def lesson_exists(dedupe_key: str) -> Optional[Dict[str, Any]]:
    if not dedupe_key:
        return None
    for lesson in reversed(_read_jsonl(LESSONS_PATH)):
        if lesson.get("dedupe_key") == dedupe_key:
            return lesson
    return None


def record_lesson(
    *,
    source: str,
    title: str,
    summary: str,
    tags: Optional[List[str]] = None,
    confidence: float = 0.5,
    evidence_paths: Optional[List[str]] = None,
    dedupe_key: Optional[str] = None,
) -> Dict[str, Any]:
    ensure_hermes_dir()
    existing = lesson_exists(dedupe_key) if dedupe_key else None
    if existing:
        payload = dict(existing)
        payload["_existing"] = True
        return payload
    trusted_evidence_paths = _filter_trusted_evidence_paths(evidence_paths)
    source_name = str(source)
    if not trusted_evidence_paths and source_name not in TRUSTED_LESSON_SOURCES:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "source": source_name,
            "title": title,
            "summary": summary,
            "tags": tags or [],
            "confidence": round(float(confidence), 2),
            "evidence_paths": [],
            "trusted_artifacts": False,
            "_existing": False,
            "_skipped_untrusted": True,
        }
        if dedupe_key:
            payload["dedupe_key"] = dedupe_key
        return payload
    payload = {
        "timestamp": datetime.now().isoformat(),
        "source": source_name,
        "title": title,
        "summary": summary,
        "tags": tags or [],
        "confidence": round(float(confidence), 2),
        "evidence_paths": trusted_evidence_paths,
        "trusted_artifacts": True,
    }
    if dedupe_key:
        payload["dedupe_key"] = dedupe_key
    with LESSONS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    payload["_existing"] = False
    return payload


def select_relevant_skills(user_text: str, limit: int = 3) -> List[Dict[str, Any]]:
    text = (user_text or "").lower()
    scored: List[tuple[int, Dict[str, Any]]] = []
    for skill in load_skill_registry():
        triggers = [str(trigger).lower() for trigger in skill.get("triggers", [])]
        score = sum(1 for trigger in triggers if trigger and trigger in text)
        if score > 0:
            scored.append((score, skill))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [skill for _, skill in scored[:limit]]


def build_hermes_grounding(user_text: str, lesson_limit: int = 4) -> str:
    skills = select_relevant_skills(user_text)
    lessons = load_lessons(limit=lesson_limit, trusted_only=True)
    blocks: List[str] = []

    if skills:
        skill_lines = []
        for skill in skills:
            guidance = skill.get("guidance", [])[:2]
            joined_guidance = " | ".join(str(item) for item in guidance)
            skill_lines.append(f"- {skill.get('name', skill.get('slug', 'skill'))}: {skill.get('summary', '')} {joined_guidance}".strip())
        blocks.append("[HERMES SKILLS]\n" + "\n".join(skill_lines))

    if lessons:
        lesson_lines = []
        for lesson in lessons:
            lesson_lines.append(
                f"- {lesson.get('title', 'Lesson')}: {lesson.get('summary', '')} (source: {lesson.get('source', 'unknown')}, confidence: {lesson.get('confidence', 0)})"
            )
        blocks.append("[HERMES LESSONS]\n" + "\n".join(lesson_lines))

    return "\n\n".join(blocks).strip()


def get_hermes_memory_snapshot() -> Dict[str, Any]:
    skills = load_skill_registry()
    lessons = load_lessons(limit=20, trusted_only=True)
    operational_memory = load_operational_memory()
    by_source: Dict[str, int] = {}
    for lesson in load_lessons(limit=-1, trusted_only=True):
        source = str(lesson.get("source", "unknown"))
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "skills": skills,
        "skills_count": len(skills),
        "recent_lessons": lessons,
        "lessons_count": len(lessons),
        "lessons_by_source": by_source,
        "operational_memory": operational_memory,
        "files": {
            "skills_config": str(SKILLS_PATH),
            "lessons_path": str(LESSONS_PATH),
            "operational_memory_path": str(OPERATIONAL_MEMORY_PATH),
        },
    }
