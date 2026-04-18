import os
import re
import subprocess
import sys
from typing import Any, Dict, Optional


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

FOUNDER_EMAIL = "aifusionlabs@gmail.com"
DEFAULT_ACK_BODY = "I have your note and I'm on it."


def extract_founder_reply_request(user_msg: str) -> Optional[Dict[str, str]]:
    text = (user_msg or "").strip()
    lowered = text.lower()
    if not any(token in lowered for token in ("reply", "respond")):
        return None
    if "email" not in lowered:
        return None
    founder_markers = (
        "my email",
        "my last email",
        "my latest email",
        "email from me",
        "last email from me",
        "latest email from me",
        "reply to me",
        FOUNDER_EMAIL,
    )
    if not any(marker in lowered for marker in founder_markers):
        return None

    body = None
    patterns = [
        r"(?:and say|saying|say|with|that says?|to say)\s+(.+)$",
        r"(?:reply|respond)(?:\s+to)?(?:\s+my)?(?:\s+last|\s+latest)?\s+email(?:\s+from\s+me)?\s+(?:with|saying|and say)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            body = match.group(1).strip().strip("\"'")
            break
    if not body:
        body = DEFAULT_ACK_BODY
    return {"sender": FOUNDER_EMAIL, "body": body}


def founder_reply_succeeded(dispatch: Dict[str, Any]) -> bool:
    if int(dispatch.get("returncode", 1)) != 0:
        return False
    stdout = str(dispatch.get("stdout", "") or "").lower()
    stderr = str(dispatch.get("stderr", "") or "").lower()
    if "founder-only reply is locked" in stdout or "founder-only reply is locked" in stderr:
        return False
    if "reply sent to" in stdout and "successfully" in stdout:
        return True
    failure_markers = (
        "failed to connect",
        "timeout",
        "error replying",
        "no founder email thread",
        "could not locate",
    )
    return not any(marker in f"{stdout} {stderr}" for marker in failure_markers)


def dispatch_founder_reply(
    body: str,
    sender: str = FOUNDER_EMAIL,
    *,
    runner=subprocess.run,
) -> Dict[str, Any]:
    sender = (sender or "").strip().lower()
    if sender != FOUNDER_EMAIL:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": f"Founder-only reply is locked to {FOUNDER_EMAIL}.",
            "success": False,
        }
    args = [
        PYTHON_EXE,
        os.path.join(ROOT_DIR, "tools", "gsuite_handler.py"),
        "--action",
        "gmail_reply_founder_latest",
        "--sender",
        sender,
        "--body",
        body,
    ]
    proc = runner(args, capture_output=True, text=True, cwd=ROOT_DIR)
    dispatch = {
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }
    dispatch["success"] = founder_reply_succeeded(dispatch)
    return dispatch
