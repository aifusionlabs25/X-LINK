import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class HermesExecutionPolicy:
    allow_outbound_email: bool = True
    allow_browser_scout: bool = True
    allow_board_briefing: bool = False


class HermesActionExecutor:
    """Hermes-native action executor with a narrow explicit allowlist."""

    ALLOWED_ACTIONS = {
        "TEST_SESSION_CREATE",
        "TEST_SESSION_STATUS",
        "TEST_SESSION_REPORT",
        "TEST_SESSION_EMAIL",
        "TEST_SESSION_DIGEST_EMAIL",
        "FOUNDER_EMAIL_REPLY",
        "GSUITE_INTENT",
        "BROWSER_SCOUT",
        "EXEC_AUDIT",
        "SYNC_ENGINES",
        "GEN_BRIEFING",
        "EXEC_ARCHIVE",
    }

    ALLOWED_GSUITE_INTENTS = {"gmail_send", "gmail_list", "gmail_read_latest", "calendar_create"}

    def __init__(self, *, root_dir: str, python_exe: str, policy: Optional[HermesExecutionPolicy] = None):
        self.root_dir = root_dir
        self.python_exe = python_exe
        self.policy = policy or HermesExecutionPolicy()

    def execute(self, action: str, args: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        action = str(action or "").strip()
        args = dict(args or {})
        context = dict(context or {})

        if action not in self.ALLOWED_ACTIONS:
            raise ValueError(f"Hermes executor blocked unsupported action: {action}")

        if action == "TEST_SESSION_CREATE":
            return self._execute_test_session_create(args, context)
        if action == "TEST_SESSION_STATUS":
            return self._execute_test_session_status(args)
        if action == "TEST_SESSION_REPORT":
            return self._execute_test_session_report(args)
        if action == "TEST_SESSION_EMAIL":
            return self._execute_test_session_email(args)
        if action == "TEST_SESSION_DIGEST_EMAIL":
            return self._execute_test_session_digest_email(args)
        if action == "FOUNDER_EMAIL_REPLY":
            return self._execute_founder_email_reply(args)
        if action == "GSUITE_INTENT":
            return self._execute_gsuite(args)
        if action == "BROWSER_SCOUT":
            return self._execute_browser_scout(args)
        if action in {"EXEC_AUDIT", "SYNC_ENGINES", "GEN_BRIEFING", "EXEC_ARCHIVE"}:
            return self._execute_background_tool(action, args, context)

        raise ValueError(f"Hermes executor has no handler for action: {action}")

    def _execute_test_session_create(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        from tools.hermes_operator import execute_operator_plan, plan_operator_mission, render_operator_reply

        mission_request = str(args.get("request") or context.get("user_msg") or "Run a test operator mission.").strip()
        plan = plan_operator_mission(
            mission_request,
            {
                "requested_by": context.get("requested_by", "Rob"),
                "persona": context.get("persona", "sloane"),
                "target_agent": args.get("target_agent") or args.get("agent") or "dani",
                "intent_hint": "test_session_create",
                "source": context.get("source", "hermes_executor"),
                "chat_history": context.get("chat_history") or [],
            },
        )
        result = execute_operator_plan(plan, {"args": args, "start": True})
        return {
            "reply": render_operator_reply(result, persona=context.get("persona", "sloane")),
            "job_id": result["job"]["job_id"],
            "job": result["job"],
            "result": result,
        }

    def _execute_test_session_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from tools.sloane_jobs import list_jobs, load_job

        job_id = args.get("job_id")
        job = load_job(job_id) if job_id else (list_jobs(limit=1)[0] if list_jobs(limit=1) else None)
        if not job:
            return {"reply": "No Sloane test operator job is currently on record."}
        return {"reply": f"Test Operator job {job['job_id']} is {job['phase']}. Current target is {job['spec']['target_agent']}.", "job": job}

    def _execute_test_session_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from tools.sloane_jobs import list_jobs, load_job

        job_id = args.get("job_id")
        job = load_job(job_id) if job_id else (list_jobs(limit=1)[0] if list_jobs(limit=1) else None)
        if not job:
            return {"reply": "No completed Sloane test operator report is available yet."}
        report_path = job.get("artifacts", {}).get("report_text")
        if report_path and os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as rf:
                return {"reply": rf.read()[:4000], "job": job}
        return {"reply": "That mission does not have a saved report yet.", "job": job}

    def _execute_test_session_email(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from tools.sloane_jobs import approve_job_email

        job_id = args.get("job_id")
        if not job_id:
            return {"reply": "I need a job id before I can approve that outbound report."}
        try:
            job = approve_job_email(job_id)
        except FileNotFoundError:
            return {"reply": f"I could not find a Sloane job with id {job_id}."}
        email_status = job.get("results", {}).get("email", {}).get("status", "unknown")
        return {"reply": f"Understood. Job {job_id} email action is now {email_status}.", "job": job}

    def _execute_test_session_digest_email(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from tools.sloane_jobs import _dispatch_email, build_test_session_digest, parse_requested_date

        target_date = parse_requested_date(args.get("target_date", ""))
        recipient = str(args.get("recipient") or "aifusionlabs@gmail.com").strip().lower()
        if not target_date:
            return {"reply": "I need a valid date before I can send that test-session digest."}
        digest = build_test_session_digest(target_date, recipient)
        if not self.policy.allow_outbound_email:
            return {"reply": "Hermes execution policy blocked outbound email for this digest.", "digest": digest}
        dispatch = _dispatch_email(digest["subject"], digest["body"], recipient)
        if dispatch.get("success"):
            return {"reply": f"Understood. I sent the {target_date.strftime('%B %d, %Y')} test-session digest to {recipient}.", "dispatch": dispatch}
        return {"reply": f"I prepared the {target_date.strftime('%B %d, %Y')} test-session digest, but the send failed.", "dispatch": dispatch}

    def _execute_founder_email_reply(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from tools.founder_email import dispatch_founder_reply

        body = str(args.get("body") or "").strip()
        if not body:
            return {"reply": "I need the reply text before I can answer your latest email."}
        if not self.policy.allow_outbound_email:
            return {"reply": "Hermes execution policy blocked outbound founder reply."}
        dispatch = dispatch_founder_reply(body)
        if dispatch.get("success"):
            return {"reply": "Done. I replied to your latest email.", "dispatch": dispatch}
        return {"reply": "I prepared the founder reply, but the Gmail thread reply failed.", "dispatch": dispatch}

    def _execute_gsuite(self, args: Dict[str, Any]) -> Dict[str, Any]:
        intent = str(args.get("intent") or "").strip()
        if intent not in self.ALLOWED_GSUITE_INTENTS:
            raise ValueError(f"Unknown GSUITE_INTENT intent: {intent}. Use gmail_send, gmail_list, gmail_read_latest, or calendar_create.")

        g_args = [self.python_exe, os.path.join(self.root_dir, "tools", "gsuite_handler.py"), "--action", intent]
        if intent == "gmail_send":
            if not self.policy.allow_outbound_email:
                return {"reply": "Hermes execution policy blocked outbound Gmail send."}
            to_addr = args.get("target")
            if not to_addr:
                raise ValueError("gmail_send requires 'target' (recipient email address)")
            subject = args.get("subject", "Message from Sloane")
            body = args.get("body", args.get("constraints", ""))
            g_args += ["--to", to_addr, "--subject", subject, "--body", body]
            subprocess.Popen(g_args, cwd=self.root_dir)
            return {"reply": f"Acknowledged. GSuite mission dispatched for {intent}."}

        if intent == "gmail_list":
            account = args.get("target") or "novaaifusionlabs@gmail.com"
            limit = str(args.get("limit") or 5)
            sender_filter = str(args.get("sender_filter") or args.get("sender") or "")
            g_args += ["--account", account, "--limit", limit]
            if sender_filter:
                g_args += ["--sender-filter", sender_filter]
            proc = subprocess.run(g_args, capture_output=True, text=True, cwd=self.root_dir)
            try:
                payload = json.loads((proc.stdout or "").strip() or "{}")
            except json.JSONDecodeError:
                payload = {"success": False, "error": (proc.stdout or proc.stderr or "").strip(), "entries": []}
            if not payload.get("success"):
                error_text = payload.get("error") or (proc.stderr or "Inbox inspection failed.")
                return {"reply": f"I tried to check the inbox, but the read failed: {error_text}", "gmail_list": payload}
            entries = payload.get("entries") or []
            if not entries:
                return {"reply": "I checked the inbox. Nothing new is waiting at the moment.", "gmail_list": payload}
            top = entries[0]
            sender = top.get("sender") or "unknown sender"
            subject = top.get("subject") or "No subject"
            count = payload.get("count", len(entries))
            return {
                "reply": f"Yes. I checked the inbox. The latest message is from {sender} with subject '{subject}'. I can see {count} recent message{'s' if count != 1 else ''}.",
                "gmail_list": payload,
            }

        if intent == "gmail_read_latest":
            account = args.get("target") or "novaaifusionlabs@gmail.com"
            query = str(args.get("query") or "")
            sender_filter = str(args.get("sender_filter") or args.get("sender") or "")
            g_args += ["--account", account]
            if query:
                g_args += ["--query", query]
            if sender_filter:
                g_args += ["--sender-filter", sender_filter]
            proc = subprocess.run(g_args, capture_output=True, text=True, cwd=self.root_dir)
            try:
                payload = json.loads((proc.stdout or "").strip() or "{}")
            except json.JSONDecodeError:
                payload = {"success": False, "error": (proc.stdout or proc.stderr or "").strip()}
            if not payload.get("success"):
                error_text = payload.get("error") or (proc.stderr or "Inbox detail read failed.")
                return {"reply": f"I tried to read the latest matching email, but the read failed: {error_text}", "gmail_read_latest": payload}
            subject = payload.get("subject") or "No subject"
            sender = payload.get("sender") or "unknown sender"
            body = str(payload.get("body") or "").strip()
            if body:
                preview = body[:220].replace("\n", " ").strip()
                reply = f"I pulled the latest matching email from {sender} with subject '{subject}'. Preview: {preview}"
            else:
                reply = f"I pulled the latest matching email from {sender} with subject '{subject}'."
            return {
                "reply": reply,
                "gmail_read_latest": payload,
            }

        title = args.get("target", "Sloane Meeting")
        description = args.get("description", args.get("constraints", ""))
        g_args += ["--title", title, "--description", description]
        subprocess.Popen(g_args, cwd=self.root_dir)
        return {"reply": f"Acknowledged. GSuite mission dispatched for {intent}."}

    def _execute_browser_scout(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.policy.allow_browser_scout:
            return {"reply": "Hermes execution policy blocked browser scouting."}
        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("browser_scout requires 'url'")
        subprocess.Popen(
            [self.python_exe, os.path.join(self.root_dir, "tools", "browser_scout.py"), "--url", url],
            cwd=self.root_dir,
        )
        return {"reply": f"Acknowledged. Scouting the target URL: {url}. I'll inform you when the intelligence is archived."}

    def _execute_background_tool(self, action: str, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if action == "EXEC_ARCHIVE":
            return self._execute_archive(args, context)

        tool_map = {
            "EXEC_AUDIT": ("tools/usage_auditor.py", []),
            "SYNC_ENGINES": ("tools/usage_auditor.py", []),
            "GEN_BRIEFING": ("tools/executive_briefing.py", []),
        }
        script, extra_args = tool_map[action]
        proc = subprocess.Popen(
            [self.python_exe, os.path.join(self.root_dir, script)] + list(extra_args),
            cwd=self.root_dir,
        )

        user_msg = str(context.get("user_msg") or "").strip()
        query = str(args.get("query") or args.get("target") or "").strip()
        if not query and user_msg:
            match = re.search(r"\bfor\s+([A-Za-z0-9& ._-]+?)(?:\s+in\s+our|\s*\?|$)", user_msg, re.IGNORECASE)
            if match:
                query = match.group(1).strip()

        if action in {"EXEC_AUDIT", "SYNC_ENGINES"} and query:
            reply = f"I've dispatched the usage audit to check for {query} and refresh the dashboard."
        elif action == "GEN_BRIEFING":
            reply = "I'm refreshing the executive briefing for the Hub now."
        elif action == "EXEC_ARCHIVE":
            reply = "I've dispatched the archive sweep."
        else:
            reply = f"Acknowledged. Initiating {action} mission background..."

        return {
            "reply": reply,
            "tool_key": os.path.splitext(os.path.basename(script))[0],
            "pid": proc.pid,
        }

    def _execute_archive(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        folder_patterns = (
            re.compile(r'from\s+"([^"]+)"', re.IGNORECASE),
            re.compile(r"from\s+'([^']+)'", re.IGNORECASE),
            re.compile(r'folder\s+"([^"]+)"', re.IGNORECASE),
            re.compile(r"folder\s+'([^']+)'", re.IGNORECASE),
            re.compile(r'folder\s+named\s+"([^"]+)"', re.IGNORECASE),
            re.compile(r"folder\s+named\s+'([^']+)'", re.IGNORECASE),
            re.compile(r"in\s+the\s+ChatGPT\s+folder\s+\"([^\"]+)\"", re.IGNORECASE),
            re.compile(r"in\s+the\s+ChatGPT\s+folder\s+'([^']+)'", re.IGNORECASE),
        )

        def extract_archive_folder(prompt_text: str, explicit_folder: Optional[str] = None) -> str:
            folder = str(explicit_folder or "").strip()
            if folder:
                return folder
            prompt_clean = str(prompt_text or "").strip()
            if not prompt_clean:
                return ""
            for pattern in folder_patterns:
                match = pattern.search(prompt_clean)
                if match:
                    return str(match.group(1) or "").strip()
            return ""

        def infer_folder_from_history() -> str:
            explicit = extract_archive_folder(
                prompt,
                args.get("folder_name"),
            )
            if explicit:
                return explicit
            history = context.get("chat_history") or []
            for message in reversed(history):
                content = str(message.get("content") or "").strip()
                if not content:
                    continue
                inferred = extract_archive_folder(content, None)
                if inferred:
                    return inferred
            return ""

        user_msg = str(context.get("user_msg") or "").strip()
        prompt = str(args.get("prompt") or user_msg or "Archive the requested ChatGPT conversations.").strip()
        platform = str(args.get("platform") or "chatgpt").strip().lower()
        limit = str(args.get("limit") or 10)
        folder_name = infer_folder_from_history()

        run_id = datetime.now().strftime("archive_%Y%m%d_%H%M%S")
        run_dir = os.path.join(self.root_dir, "vault", "archives", "_runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        request_payload = {
            "prompt": prompt,
            "platform": platform,
            "keyword": args.get("keyword"),
            "folder_name": folder_name,
            "limit": limit,
            "attachments": args.get("attachments") or [],
            "attachment_context": "",
        }
        with open(os.path.join(run_dir, "request.json"), "w", encoding="utf-8") as fh:
            json.dump(request_payload, fh, indent=2)

        proc = subprocess.Popen(
            [
                self.python_exe,
                os.path.join(self.root_dir, "tools", "great_archivist.py"),
                "--run-id",
                run_id,
                "--limit",
                limit,
                "--platform",
                platform,
            ],
            cwd=self.root_dir,
        )
        reply = "I've dispatched the archive sweep."
        if folder_name:
            reply = f"I've dispatched Archive Intel for the ChatGPT folder '{folder_name}'."
        return {"reply": reply, "tool_key": "great_archivist", "pid": proc.pid, "run_id": run_id}
