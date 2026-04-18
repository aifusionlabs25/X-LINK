import asyncio
import hashlib
import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.founder_email import FOUNDER_EMAIL, dispatch_founder_reply


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

STATE_DIR = ROOT_DIR / "vault" / "sloane_inbox"
STATE_PATH = STATE_DIR / "state.json"
EVENTS_PATH = STATE_DIR / "events.jsonl"
PID_PATH = STATE_DIR / "watcher.pid"
POLL_INTERVAL_SECONDS = 60
MAX_PROCESSED = 200
BRIDGE_URL = "http://127.0.0.1:5001/api/chat"
ACCOUNT_EMAIL = "novaaifusionlabs@gmail.com"
GMAIL_INBOX_URL = f"https://mail.google.com/mail/u/{ACCOUNT_EMAIL}/#inbox"
GMAIL_FEED_URL = f"https://mail.google.com/mail/u/{ACCOUNT_EMAIL}/feed/atom"
SILENT_POLLING = True


def _now() -> str:
    return datetime.now().isoformat()


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, Any]:
    _ensure_dirs()
    if not STATE_PATH.exists():
        return {
            "running": False,
            "status": "idle",
            "last_poll_at": None,
            "last_email_at": None,
            "last_action_at": None,
            "last_error": None,
            "processed_ids": [],
            "last_event": None,
        }
    with STATE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(state: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_dirs()
    with STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    return state


def append_event(event: Dict[str, Any]) -> None:
    _ensure_dirs()
    payload = {"timestamp": _now(), **event}
    with EVENTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def trim_processed(processed_ids: List[str]) -> List[str]:
    if len(processed_ids) <= MAX_PROCESSED:
        return processed_ids
    return processed_ids[-MAX_PROCESSED:]


def build_email_fingerprint(sender: str, subject: str, preview: str, body: str) -> str:
    raw = "||".join(
        [
            (sender or "").strip().lower(),
            (subject or "").strip(),
            (preview or "").strip(),
            (body or "").strip()[:500],
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def founder_sender_matches(sender_text: str) -> bool:
    sender = (sender_text or "").strip().lower()
    if sender == ACCOUNT_EMAIL:
        return False
    return FOUNDER_EMAIL in sender


def build_founder_bridge_message(subject: str, body: str) -> str:
    return (
        "FOUNDER EMAIL RECEIVED.\n"
        f"Sender: {FOUNDER_EMAIL}\n"
        f"Subject: {subject}\n"
        "Body:\n"
        f"{body}\n\n"
        "Handle this exactly as you would a direct founder request. "
        "If a tool should run, run it. Then produce a concise email-thread reply."
    )


def execute_founder_email_action(
    subject: str,
    body: str,
    *,
    chat_post=requests.post,
    reply_dispatch=dispatch_founder_reply,
) -> Dict[str, Any]:
    bridge_message = build_founder_bridge_message(subject, body)
    response = chat_post(BRIDGE_URL, json={"message": bridge_message}, timeout=600)
    response.raise_for_status()
    payload = response.json()
    reply_text = (payload.get("reply") or "Noted.").strip()
    dispatch = reply_dispatch(reply_text, FOUNDER_EMAIL)
    return {
        "reply_text": reply_text,
        "dispatch": dispatch,
        "success": bool(dispatch.get("success")),
    }


class FounderInboxWatcher:
    def __init__(self) -> None:
        self.engine = None
        self.state = load_state()

    def _update_state(self, **updates: Any) -> None:
        self.state.update(updates)
        self.state["processed_ids"] = trim_processed(self.state.get("processed_ids", []))
        save_state(self.state)

    async def _ensure_engine(self) -> bool:
        if self.engine:
            return True
        from x_link_engine import XLinkEngine

        self.engine = XLinkEngine()
        connected = await self.engine.connect()
        if not connected:
            self._update_state(
                running=True,
                status="waiting_for_browser",
                last_poll_at=_now(),
                last_error="Failed to connect to Brave CDP.",
            )
            try:
                await self.engine.close()
            except Exception:
                pass
            self.engine = None
            return False
        return True

    async def _fetch_inbox_entries(self) -> List[Dict[str, str]]:
        if not self.engine or not self.engine.context:
            return []

        cookies = await self.engine.context.cookies([GMAIL_FEED_URL])
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

        response = session.get(GMAIL_FEED_URL, timeout=20)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        entries: List[Dict[str, str]] = []
        for entry in root.findall("{http://purl.org/atom/ns#}entry"):
            author = entry.find("{http://purl.org/atom/ns#}author")
            entries.append(
                {
                    "subject": (entry.findtext("{http://purl.org/atom/ns#}title") or "").strip(),
                    "summary": (entry.findtext("{http://purl.org/atom/ns#}summary") or "").strip(),
                    "issued": (entry.findtext("{http://purl.org/atom/ns#}issued") or "").strip(),
                    "sender": (author.findtext("{http://purl.org/atom/ns#}email") if author is not None else "") or "",
                }
            )
        return entries

    async def _process_entry(self, entry: Dict[str, str]) -> Optional[Dict[str, Any]]:
        sender = (entry.get("sender") or "").strip()
        if not founder_sender_matches(sender):
            return None

        subject = (entry.get("subject") or "").strip()
        preview = (entry.get("summary") or "").strip()
        time_label = (entry.get("issued") or "").strip()
        body = preview or subject
        fingerprint = build_email_fingerprint(sender, subject, preview or time_label, body)
        if fingerprint in self.state.get("processed_ids", []):
            return None

        action = execute_founder_email_action(subject, body)
        if action["reply_text"].strip().lower() == "done. i replied to your latest email.":
            action["success"] = False
            action["dispatch"] = {
                "success": False,
                "stdout": "",
                "stderr": "Rejected recursive founder-reply meta response.",
            }
        self.state.setdefault("processed_ids", []).append(fingerprint)
        event = {
            "type": "founder_email_processed",
            "sender": sender,
            "subject": subject,
            "fingerprint": fingerprint,
            "success": action["success"],
            "reply_preview": action["reply_text"][:200],
        }
        append_event(event)
        self._update_state(
            running=True,
            status="active",
            last_poll_at=_now(),
            last_email_at=_now(),
            last_action_at=_now(),
            last_error=None,
            last_event=event,
        )
        return event

    async def poll_once(self) -> List[Dict[str, Any]]:
        if not await self._ensure_engine():
            return []

        events: List[Dict[str, Any]] = []
        entries = await self._fetch_inbox_entries()
        for entry in entries:
            try:
                event = await self._process_entry(entry)
                if event:
                    events.append(event)
            except Exception as exc:
                logging.error(f"Founder inbox row processing failed: {exc}")
                append_event({"type": "founder_email_error", "message": str(exc)})
                self._update_state(
                    running=True,
                    status="error",
                    last_poll_at=_now(),
                    last_error=str(exc),
                )
        self._update_state(
            running=True,
            status="active",
            last_poll_at=_now(),
        )
        return events

    async def run_forever(self) -> None:
        _ensure_dirs()
        PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
        self._update_state(running=True, status="starting", last_error=None)
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                logging.error(f"Founder inbox watcher loop failed: {exc}")
                append_event({"type": "watcher_error", "message": str(exc)})
                self._update_state(
                    running=True,
                    status="error",
                    last_poll_at=_now(),
                    last_error=str(exc),
                )
                if self.engine:
                    try:
                        await self.engine.close()
                    except Exception:
                        pass
                    self.engine = None
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def main() -> None:
    watcher = FounderInboxWatcher()
    await watcher.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
