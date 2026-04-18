import argparse
import asyncio
import json
import logging
import os
import re
import string
import sys
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.report_ops import dispatch_report_email
from tools.sloane_runtime import generate_sloane_response
from tools.watch_patterns import append_watched_event, default_watch_patterns
from x_link_engine import XLinkEngine

LOG_PATH = os.path.join(ROOT_DIR, "vault", "logs", "sloane_operations.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

VAULT_DIR = os.path.join(ROOT_DIR, "vault", "archives")
RUNS_DIR = os.path.join(VAULT_DIR, "_runs")
os.makedirs(RUNS_DIR, exist_ok=True)

PARAMS_PATH = os.path.join(ROOT_DIR, "config", "archival_params.yaml")
SELECTORS_PATH = os.path.join(ROOT_DIR, "config", "archival_selectors.json")

try:
    with open(PARAMS_PATH, "r", encoding="utf-8") as fh:
        ARCHIVAL_PARAMS = yaml.safe_load(fh)
except Exception:
    ARCHIVAL_PARAMS = {"projects": [], "ignore_titles": []}

try:
    with open(SELECTORS_PATH, "r", encoding="utf-8") as fh:
        SELECTORS = json.load(fh)
except Exception:
    SELECTORS = {}

TARGETS = {
    "chatgpt": {"url": "https://chatgpt.com", "name": "ChatGPT"},
    "perplexity": {"url": "https://www.perplexity.ai", "name": "Perplexity"},
    "gemini": {"url": "https://gemini.google.com/app", "name": "Gemini"},
    "grok": {"url": "https://grok.com", "name": "Grok"},
}

CHATGPT_CONVERSATION_RE = re.compile(r"/c/[A-Za-z0-9_-]+")
CHATGPT_FOLDER_PATTERNS = (
    re.compile(r'from\s+"([^"]+)"', re.IGNORECASE),
    re.compile(r"from\s+'([^']+)'", re.IGNORECASE),
    re.compile(r'folder\s+"([^"]+)"', re.IGNORECASE),
    re.compile(r"folder\s+'([^']+)'", re.IGNORECASE),
    re.compile(r'folder\s+named\s+"([^"]+)"', re.IGNORECASE),
    re.compile(r"folder\s+named\s+'([^']+)'", re.IGNORECASE),
    re.compile(r"in\s+the\s+ChatGPT\s+folder\s+\"([^\"]+)\"", re.IGNORECASE),
    re.compile(r"in\s+the\s+ChatGPT\s+folder\s+'([^']+)'", re.IGNORECASE),
)


def _normalize_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _extract_archive_folder(prompt, explicit_folder=None):
    folder = _normalize_text(explicit_folder)
    if folder:
        return folder
    prompt_text = _normalize_text(prompt)
    if not prompt_text:
        return ""
    for pattern in CHATGPT_FOLDER_PATTERNS:
        match = pattern.search(prompt_text)
        if match:
            return _normalize_text(match.group(1))
    return ""


def _coerce_limit(raw_value, fallback=15):
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return fallback


def _is_chatgpt_conversation_url(url):
    parsed = urlparse(str(url or ""))
    if "chatgpt.com" not in parsed.netloc.lower():
        return False
    return bool(CHATGPT_CONVERSATION_RE.search(parsed.path or ""))


def _is_probably_chatgpt_noise(title="", url=""):
    if _is_chatgpt_conversation_url(url):
        return False
    joined = f"{_normalize_text(title)} {_normalize_text(url)}".lower()
    noisy_fragments = (
        "library",
        "browse and chat with your favorite",
        "/g/",
        "/gpts",
        "/discover",
        "/apps",
        "temporary chat",
        "new chat",
    )
    return any(fragment in joined for fragment in noisy_fragments)


def _chatgpt_folder_selectors(folder_name):
    folder_name = _normalize_text(folder_name)
    if not folder_name:
        return []
    return [
        f'[role="treeitem"]:has-text("{folder_name}")',
        f'[data-testid*="project"]:has-text("{folder_name}")',
        f'[data-testid*="folder"]:has-text("{folder_name}")',
        f'[aria-label="{folder_name}"]',
    ]


def _chatgpt_verified_folder_selectors(folder_name):
    folder_name = _normalize_text(folder_name)
    if not folder_name:
        return []
    return [
        f'[role="treeitem"][aria-expanded="true"]:has-text("{folder_name}")',
        f'[data-testid*="project"][aria-expanded="true"]:has-text("{folder_name}")',
        f'[data-testid*="folder"][aria-expanded="true"]:has-text("{folder_name}")',
        f'[aria-current="page"][aria-label="{folder_name}"]',
        f'[aria-selected="true"][aria-label="{folder_name}"]',
    ]


def _chatgpt_conversation_selectors(folder_name=""):
    if _normalize_text(folder_name):
        return [
            'main a[href*="/c/"]',
            '[role="main"] a[href*="/c/"]',
            'main [role="link"][href*="/c/"]',
            'main button',
            '[role="main"] button',
            'main [role="button"]',
        ]
    return [
        'nav[aria-label="Chat history"] a[href*="/c/"]',
        'aside a[href*="/c/"]',
        'a[href*="/c/"]',
    ]


def _history_selectors_for_platform(platform_key, primary_selector):
    if platform_key == "perplexity":
        return [
            primary_selector,
            "aside a[href*='/search/']",
            "nav a[href*='/search/']",
            "a[href*='/search/']",
            "a[href*='/discover/'][href*='?q=']",
        ]
    return [primary_selector]


async def _locator_exists(locator):
    try:
        return await locator.count() > 0
    except Exception:
        return False


async def _click_by_visible_text(page, text, *, container_selectors=None, exact=False):
    text = _normalize_text(text)
    if not text:
        return False
    text_match = text if exact else re.escape(text)
    candidates = []
    if container_selectors:
        for container_selector in container_selectors:
            candidates.append((page.locator(container_selector).first, container_selector))
    else:
        candidates.append((page.locator("body"), "body"))

    for container, _label in candidates:
        if not await _locator_exists(container):
            continue
        try:
            clicked = await container.evaluate(
                """({ targetText, exact }) => {
                    const norm = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const lowerTarget = norm(targetText).toLowerCase();
                    const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], [role="treeitem"], [role="link"], div, span'));
                    const matches = nodes.filter((node) => {
                        if (!node || !node.isConnected) return false;
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = node.getBoundingClientRect();
                        if (rect.width < 6 || rect.height < 6) return false;
                        const text = norm(node.innerText || node.textContent || node.getAttribute('aria-label') || '');
                        if (!text) return false;
                        const lower = text.toLowerCase();
                        return exact ? lower === lowerTarget : lower.includes(lowerTarget);
                    });
                    for (const node of matches) {
                        const interactive = node.closest('button, a, [role="button"], [role="treeitem"], [role="link"]') || node;
                        interactive.scrollIntoView({ block: 'center' });
                        interactive.click();
                        return true;
                    }
                    return false;
                }""",
                {"targetText": text, "exact": exact},
            )
            if clicked:
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


def _looks_like_chatgpt_project_row(title_text):
    text = _normalize_text(title_text)
    if not text:
        return False
    lowered = text.lower()
    noise_prefixes = (
        "new chat",
        "show project details",
        "open project icon",
        "extended thinking",
        "chats",
        "sources",
        "load more conversations",
    )
    if lowered in noise_prefixes:
        return False
    if lowered.startswith("open conversation options for "):
        return False
    if lowered.startswith("open project options for "):
        return False
    return bool(re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b", lowered)) or "branch ·" in lowered or len(text) > 18


def _should_abort_folder_scoped_collection(folder_name, focused, verified, discovered_count):
    if not _normalize_text(folder_name):
        return False
    if not focused or not verified:
        return True
    return discovered_count <= 0


class LLMArchivist:
    def __init__(self, run_id=None, email_recipient=None):
        self.engine = XLinkEngine()
        os.makedirs(VAULT_DIR, exist_ok=True)
        self.run_id = run_id or datetime.now().strftime("archive_%Y%m%d_%H%M%S")
        self.email_recipient = email_recipient
        self.run_dir = os.path.join(RUNS_DIR, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)
        self.state_path = os.path.join(self.run_dir, "state.json")
        self.request_path = os.path.join(self.run_dir, "request.json")
        self.saved_files = []
        self.save_failures = []
        self.request_data = self._load_request_data()
        self.request_spec = self._derive_request_spec()
        self._write_state(status="queued", phase="boot", detail="Archivist queued.")

    def _load_request_data(self):
        if not os.path.exists(self.request_path):
            return {}
        try:
            with open(self.request_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _write_state(self, **updates):
        state = {
            "run_id": self.run_id,
            "status": "running",
            "phase": "working",
            "detail": "",
            "current_platform": None,
            "current_title": None,
            "saved_files": self.saved_files,
            "save_failures": self.save_failures[-12:],
            "email_recipient": self.email_recipient,
            "summary_path": None,
            "email_sent": False,
            "watch_patterns": default_watch_patterns("archive"),
            "events": [],
            "matched_signals": [],
            "updated_at": datetime.now().isoformat(),
        }
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    state.update(json.load(fh))
            except Exception:
                pass
        state.update(updates)
        state["saved_files"] = self.saved_files
        state["save_failures"] = self.save_failures[-12:]
        state["updated_at"] = datetime.now().isoformat()
        state = append_watched_event(
            state,
            kind="archive",
            status=state.get("status"),
            phase=state.get("phase"),
            detail=state.get("detail"),
            source="great_archivist",
            extra={
                "current_platform": state.get("current_platform"),
                "current_title": state.get("current_title"),
                "saved_count": len(self.saved_files),
            },
        )
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        return state

    def _record_save_failure(self, title, reason, *, platform=None, url=None, exception_type=None):
        payload = {
            "title": _normalize_text(title),
            "reason": _normalize_text(reason),
            "platform": platform,
            "url": url,
            "exception_type": exception_type,
            "captured_at": datetime.now().isoformat(),
        }
        self.save_failures.append(payload)
        return payload

    async def _capture_chatgpt_folder_diagnostics(self, page, folder_name, reason):
        diagnostics_path = os.path.join(self.run_dir, "chatgpt_folder_diagnostics.json")
        os.makedirs(self.run_dir, exist_ok=True)
        folder_name = _normalize_text(folder_name)
        payload = {
            "folder_name": folder_name,
            "reason": reason,
            "captured_at": datetime.now().isoformat(),
            "page_title": None,
            "page_url": page.url,
            "visible_sidebar_candidates": [],
            "matching_folder_text": [],
            "project_related_text": [],
        }
        try:
            payload["page_title"] = await page.title()
        except Exception:
            pass
        try:
            payload.update(
                await page.evaluate(
                    """(targetText) => {
                        const norm = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                        const target = norm(targetText).toLowerCase();
                        const selectors = [
                            'nav[aria-label="Chat history"]',
                            'aside',
                            '[role="navigation"]',
                            'body',
                        ];
                        const seen = new Set();
                        const sidebarCandidates = [];
                        const folderMatches = [];
                        const projectRelated = [];
                        for (const selector of selectors) {
                            const root = document.querySelector(selector);
                            if (!root) continue;
                            const nodes = root.querySelectorAll('button, a, [role="button"], [role="treeitem"], [role="link"], [aria-label], h1, h2, h3, [role="heading"], div, span');
                            for (const node of nodes) {
                                const style = window.getComputedStyle(node);
                                if (style.display === 'none' || style.visibility === 'hidden') continue;
                                const rect = node.getBoundingClientRect();
                                if (rect.width < 6 || rect.height < 6) continue;
                                const text = norm(node.innerText || node.textContent || node.getAttribute('aria-label') || '');
                                if (!text || seen.has(text)) continue;
                                seen.add(text);
                                if (sidebarCandidates.length < 80) sidebarCandidates.push(text);
                                const lower = text.toLowerCase();
                                if (target && lower.includes(target) && folderMatches.length < 25) {
                                    folderMatches.push(text);
                                }
                                if ((lower.includes('project') || lower.includes('projects') || lower.includes('folder')) && projectRelated.length < 25) {
                                    projectRelated.push(text);
                                }
                            }
                        }
                        return {
                            visible_sidebar_candidates: sidebarCandidates,
                            matching_folder_text: folderMatches,
                            project_related_text: projectRelated,
                        };
                    }""",
                    folder_name,
                )
            )
        except Exception as exc:
            payload["diagnostic_error"] = str(exc)

        with open(diagnostics_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        self._write_state(diagnostics_path=diagnostics_path)
        return diagnostics_path

    async def _capture_history_diagnostics(self, page, platform_key, reason):
        diagnostics_path = os.path.join(self.run_dir, f"{platform_key}_history_diagnostics.json")
        payload = {
            "platform": platform_key,
            "reason": reason,
            "captured_at": datetime.now().isoformat(),
            "page_title": None,
            "page_url": page.url,
            "visible_history_candidates": [],
        }
        try:
            payload["page_title"] = await page.title()
        except Exception:
            pass
        try:
            payload["visible_history_candidates"] = await page.evaluate(
                """() => {
                    const norm = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const anchors = Array.from(document.querySelectorAll("a"));
                    return anchors
                        .map((node) => ({
                            text: norm(node.innerText || node.textContent || node.getAttribute("aria-label") || ""),
                            href: node.getAttribute("href") || "",
                        }))
                        .filter((entry) => entry.text || entry.href)
                        .slice(0, 200);
                }"""
            )
        except Exception:
            pass
        with open(diagnostics_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        self._write_state(diagnostics_path=diagnostics_path)
        return diagnostics_path

    def _derive_request_spec(self):
        prompt = self.request_data.get("prompt") or ""
        folder_name = _extract_archive_folder(prompt, self.request_data.get("folder_name"))
        return {
            "prompt": prompt,
            "folder_name": folder_name,
            "limit": _coerce_limit(self.request_data.get("limit"), 15),
        }

    async def connect(self):
        logging.info("Initializing The Great Archivist engine...")
        self._write_state(status="running", phase="connecting", detail="Connecting to automation browser...")
        return await self.engine.connect()

    async def disconnect(self):
        await self.engine.close()

    def _sanitize_filename(self, text):
        valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
        cleaned = "".join(c for c in text if c in valid_chars)
        return cleaned.strip()[:50] or "untitled_session"

    async def _extract_page_snapshot(self, page, platform_name, selectors=None):
        content = ""
        if selectors:
            try:
                await page.wait_for_selector(selectors["message_containers"], timeout=5000)
                containers = await page.locator(selectors["message_containers"]).all()
                dialogue = []
                for container in containers:
                    user_count = await container.locator(selectors["user_message_text"]).count()
                    ai_count = await container.locator(selectors["ai_message_text"]).count()
                    user_text = "\n".join(await container.locator(selectors["user_message_text"]).all_inner_texts()) if user_count > 0 else None
                    ai_text = "\n".join(await container.locator(selectors["ai_message_text"]).all_inner_texts()) if ai_count > 0 else None
                    if user_text:
                        dialogue.append(f"#### [User]:\n{user_text.strip()}\n")
                    if ai_text:
                        dialogue.append(f"#### [{platform_name}]:\n{ai_text.strip()}\n")
                content = "\n".join(dialogue).strip()
            except Exception as exc:
                logging.warning(f"Targeted extraction failed for {platform_name}, falling back to raw text. ({exc})")

        fallback_selectors = ["main", "body"]
        if not content:
            for selector in fallback_selectors:
                try:
                    content = (await page.inner_text(selector)).strip()
                    if content:
                        break
                except Exception:
                    continue

        if not content:
            try:
                raw_html = await page.content()
                content = raw_html.strip()
            except Exception:
                content = ""

        return content.strip()

    def _trigger_intervention(self, service_name, url, issue, message=None, action_label=None):
        logging.warning(f"INTERVENTION DETECTED: {issue} at {service_name}")
        try:
            requests.post(
                "http://127.0.0.1:5001/api/intervention",
                json={
                    "url": url,
                    "service": service_name,
                    "issue": issue,
                    "message": message or f"Founder, I'm stuck at the {service_name} gate due to a {issue}. Please handle the MFA/Login and click 'Resume Mission' so I can finish the archive.",
                    "action_label": action_label or "Done | Resume Mission",
                },
                timeout=5,
            )
        except Exception as exc:
            logging.error(f"Failed to post intervention alert: {exc}")

    async def _wait_for_intervention(self):
        logging.info("Archivist paused. Waiting for Founder to click 'Resume Mission' on the Hub...")
        while True:
            try:
                resp = requests.get("http://127.0.0.1:5001/api/intervention", timeout=5)
                data = resp.json()
                if not data.get("active"):
                    logging.info("Intervention cleared. Resuming mission...")
                    return True
            except Exception as exc:
                logging.error(f"Intervention poll failed: {exc}")
            await asyncio.sleep(2)

    async def _request_chatgpt_folder_confirmation(self, page, folder_name):
        folder_name = _normalize_text(folder_name)
        if not folder_name:
            return False
        await page.bring_to_front()
        self._write_state(
            status="running",
            phase="folder_confirmation",
            detail=f"Waiting for Founder to confirm ChatGPT folder '{folder_name}'.",
            current_platform="ChatGPT",
        )
        self._trigger_intervention(
            "ChatGPT",
            page.url,
            "Folder Selection Required",
            message=(
                f"Please select the ChatGPT Projects folder '{folder_name}' in the open ChatGPT tab, "
                "leave that folder active, then click confirm so Archive Intel can continue inside that folder only."
            ),
            action_label=f"Confirm {folder_name} | Resume Archive",
        )
        await self._wait_for_intervention()
        await asyncio.sleep(1.5)
        return True

    async def _archive_page_content(self, page, platform_name, *, allow_chatgpt_project_capture=False, title_override=None):
        try:
            title = title_override or await page.title()
            current_url = page.url
            safe_title = self._sanitize_filename(title)
            ignore_titles = ARCHIVAL_PARAMS.get("ignore_titles", [])
            if any(ign.lower() == title.lower() for ign in ignore_titles):
                logging.info(f"Skipping ignored title: {title}")
                self._record_save_failure(title, "Ignored title matched archival ignore list.", platform=platform_name, url=current_url)
                return None
            if platform_name.lower() == "chatgpt":
                is_project_capture = allow_chatgpt_project_capture and "/project" in current_url
                if (not is_project_capture and not _is_chatgpt_conversation_url(current_url)) or (not is_project_capture and _is_probably_chatgpt_noise(title, current_url)):
                    logging.info(f"Skipping non-conversation ChatGPT page: {title} ({current_url})")
                    self._record_save_failure(title, "ChatGPT page did not qualify as a verified conversation capture.", platform=platform_name, url=current_url)
                    return None

            vault_tier = "private"
            project_subfolder = ""
            for proj in ARCHIVAL_PARAMS.get("projects", []):
                if any(kw.lower() in title.lower() for kw in proj.get("keywords", [])):
                    vault_tier = "projects"
                    project_subfolder = self._sanitize_filename(proj.get("name", "Unknown"))
                    break

            platform_key = platform_name.lower()
            selectors = SELECTORS.get(platform_key)
            content = await self._extract_page_snapshot(page, platform_name, selectors=selectors)
            if allow_chatgpt_project_capture and not content:
                content = (
                    f"Project-scoped ChatGPT capture for '{title}'.\n\n"
                    f"Current URL: {current_url}\n"
                    "The project row was opened successfully, but ChatGPT did not expose a readable conversation body."
                )
            if not content:
                logging.warning(f"Skipping empty archive payload for {platform_name}: {title} ({current_url})")
                self._record_save_failure(title, "Page snapshot produced no readable content.", platform=platform_name, url=current_url)
                return None

            file_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if vault_tier == "projects":
                target_dir = os.path.join(VAULT_DIR, "projects", project_subfolder, platform_key)
            else:
                target_dir = os.path.join(VAULT_DIR, "private", platform_key)
            os.makedirs(target_dir, exist_ok=True)
            file_path = os.path.join(target_dir, f"{safe_title}_{file_stamp}.md")

            routing_badge = f"PROJECT: {project_subfolder}" if vault_tier == "projects" else "PRIVATE VAULT"
            header = (
                f"# Session Archive: {title}\n"
                f"**[DATE: {datetime.now():%Y-%m-%d}] [TIME: {datetime.now():%H:%M:%S}] [PLATFORM: {platform_name}] [ROUTING: {routing_badge}]**\n\n"
                "---\n\n"
            )
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(header + content)

            self.saved_files.append(file_path)
            self._write_state(
                phase="archiving",
                detail=f"Saved {os.path.basename(file_path)}",
                current_platform=platform_name,
            )
            logging.info(f"Archived session to {routing_badge}: {file_path}")
            return file_path
        except Exception as exc:
            logging.error(f"Failed to archive {platform_name}: {exc}")
            self._record_save_failure(title_override or "unknown archive target", str(exc), platform=platform_name, exception_type=type(exc).__name__)
            return None

    async def _open_chatgpt_folder(self, page, folder_name):
        folder_name = _normalize_text(folder_name)
        if not folder_name:
            return False

        existing_project_visible = await _click_by_visible_text(
            page,
            folder_name,
            container_selectors=['nav[aria-label="Chat history"]', 'aside', '[role="navigation"]'],
            exact=True,
        )
        if existing_project_visible:
            logging.info("Focused ChatGPT folder/project directly: %s", folder_name)
            await asyncio.sleep(2)
            return True

        await _click_by_visible_text(
            page,
            "Projects",
            container_selectors=['nav[aria-label="Chat history"]', 'aside', '[role="navigation"]'],
            exact=True,
        )

        container_selectors = [
            'nav[aria-label="Chat history"]',
            'aside',
            '[role="navigation"]',
        ]
        for container_selector in container_selectors:
            container = page.locator(container_selector).first
            if not await _locator_exists(container):
                continue
            last_scroll = None
            for _ in range(16):
                for selector in _chatgpt_folder_selectors(folder_name):
                    try:
                        locator = container.locator(selector).first
                        if await _locator_exists(locator):
                            await locator.click()
                            await asyncio.sleep(3)
                            logging.info("Focused ChatGPT folder/project: %s", folder_name)
                            return True
                    except Exception:
                        continue
                try:
                    scroll_top = await container.evaluate(
                        """node => {
                            const before = node.scrollTop || 0;
                            node.scrollBy(0, 700);
                            return { before, after: node.scrollTop || 0 };
                        }"""
                    )
                    if last_scroll == scroll_top.get("after") or scroll_top.get("before") == scroll_top.get("after"):
                        break
                    last_scroll = scroll_top.get("after")
                    await asyncio.sleep(0.6)
                except Exception:
                    break

        if await _click_by_visible_text(
            page,
            folder_name,
            container_selectors=['nav[aria-label="Chat history"]', 'aside', '[role="navigation"]'],
        ):
            logging.info("Focused ChatGPT folder/project via visible-text search: %s", folder_name)
            await asyncio.sleep(2)
            return True

        logging.warning("Could not positively focus ChatGPT folder/project: %s", folder_name)
        return False

    async def _verify_chatgpt_folder_context(self, page, folder_name):
        folder_name = _normalize_text(folder_name)
        if not folder_name:
            return True

        container_selectors = [
            'nav[aria-label="Chat history"]',
            'aside',
            '[role="navigation"]',
        ]
        for container_selector in container_selectors:
            container = page.locator(container_selector).first
            if not await _locator_exists(container):
                continue
            for selector in _chatgpt_verified_folder_selectors(folder_name):
                try:
                    locator = container.locator(selector).first
                    if await _locator_exists(locator):
                        return True
                except Exception:
                    continue
        try:
            verified = await page.evaluate(
                """(targetText) => {
                    const norm = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const target = norm(targetText);
                    const nodes = Array.from(document.querySelectorAll('[aria-current="page"], [aria-selected="true"], [aria-expanded="true"], h1, h2, [role="heading"]'));
                    return nodes.some((node) => norm(node.innerText || node.textContent || node.getAttribute('aria-label') || '').includes(target));
                }""",
                folder_name,
            )
            if verified:
                return True
        except Exception:
            pass
        try:
            visible_project_presence = await page.evaluate(
                """(targetText) => {
                    const norm = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const target = norm(targetText);
                    const navRoots = Array.from(document.querySelectorAll('nav[aria-label="Chat history"], aside, [role="navigation"]'));
                    return navRoots.some((root) => {
                        const text = norm(root.innerText || root.textContent || '');
                        if (!text.includes('projects') || !text.includes(target)) return false;
                        const exactNodes = Array.from(root.querySelectorAll('button, a, [role="button"], [role="treeitem"], [role="link"], div, span'));
                        return exactNodes.some((node) => norm(node.innerText || node.textContent || node.getAttribute('aria-label') || '') === target);
                    });
                }""",
                folder_name,
            )
            if visible_project_presence:
                return True
        except Exception:
            pass
        return False

    async def _collect_chatgpt_history(self, page, target_keyword=None, args_limit=15):
        folder_name = self.request_spec.get("folder_name")
        folder_focused = False
        folder_verified = False
        if folder_name:
            self._write_state(
                phase="folder_focus",
                detail=f"ChatGPT: waiting for manual confirmation of folder '{folder_name}'",
                current_platform="ChatGPT",
            )
            folder_focused = await self._request_chatgpt_folder_confirmation(page, folder_name)
            folder_verified = await self._verify_chatgpt_folder_context(page, folder_name)
            if not folder_focused or not folder_verified:
                diagnostics_path = await self._capture_chatgpt_folder_diagnostics(
                    page,
                    folder_name,
                    "folder_unverified",
                )
                detail = f"ChatGPT folder '{folder_name}' could not be verified. Archive aborted to avoid collecting unrelated chats."
                self._write_state(
                    status="error",
                    phase="folder_unverified",
                    detail=f"{detail} Diagnostics: {diagnostics_path}",
                    current_platform="ChatGPT",
                )
                logging.warning(detail)
                return 0
            project_page_url = page.url
        else:
            project_page_url = page.url

        link_selectors = _chatgpt_conversation_selectors(folder_name)
        discovered = []
        seen_urls = set()
        for selector in link_selectors:
            try:
                items = page.locator(selector)
                count = await items.count()
            except Exception:
                continue
            for i in range(count):
                item = items.nth(i)
                try:
                    href = await item.get_attribute("href")
                    if not href:
                        continue
                    absolute_url = urljoin("https://chatgpt.com", href)
                    if absolute_url in seen_urls or not _is_chatgpt_conversation_url(absolute_url):
                        continue
                    title_text = _normalize_text(await item.inner_text())
                    if not title_text or _is_probably_chatgpt_noise(title_text, absolute_url):
                        continue
                    if target_keyword and target_keyword.lower() not in title_text.lower():
                        continue
                    seen_urls.add(absolute_url)
                    discovered.append({"title": title_text, "url": absolute_url})
                except Exception:
                    continue
            if discovered:
                break

        if folder_name and not discovered:
            project_row_selectors = [
                'main button',
                '[role="main"] button',
                'main [role="button"]',
                'main li',
                '[role="main"] li',
            ]
            for selector in project_row_selectors:
                try:
                    items = page.locator(selector)
                    count = await items.count()
                except Exception:
                    continue
                for i in range(count):
                    item = items.nth(i)
                    try:
                        title_text = _normalize_text(await item.inner_text())
                        if not _looks_like_chatgpt_project_row(title_text):
                            continue
                        if target_keyword and target_keyword.lower() not in title_text.lower():
                            continue
                        if any(existing.get("title") == title_text for existing in discovered):
                            continue
                        discovered.append({"title": title_text, "url": None, "selector_mode": True, "index": i, "selector": selector})
                    except Exception:
                        continue
                if discovered:
                    break

        sweep_limit = _coerce_limit(args_limit, self.request_spec.get("limit", 15))
        discovered = discovered[:sweep_limit]
        if _should_abort_folder_scoped_collection(folder_name, folder_focused, folder_verified, len(discovered)):
            diagnostics_path = await self._capture_chatgpt_folder_diagnostics(
                page,
                folder_name,
                "folder_empty",
            )
            detail = f"ChatGPT folder '{folder_name}' did not yield verified conversation links. Archive aborted to avoid unrelated captures."
            self._write_state(
                status="error",
                phase="folder_empty",
                detail=f"{detail} Diagnostics: {diagnostics_path}",
                current_platform="ChatGPT",
            )
            logging.warning(detail)
            return 0
        self._write_state(
            phase="history_scan",
            detail=f"ChatGPT: found {len(discovered)} conversation chats",
            current_platform="ChatGPT",
        )

        for entry in discovered:
            title_text = entry["title"]
            target_url = entry["url"]
            try:
                self._write_state(
                    phase="history_item",
                    detail=f"ChatGPT: archiving '{title_text[:90]}'",
                    current_platform="ChatGPT",
                    current_title=title_text,
                )
                if entry.get("selector_mode"):
                    row = page.locator(entry["selector"]).nth(entry["index"])
                    await row.scroll_into_view_if_needed()
                    await row.click()
                    await asyncio.sleep(4)
                else:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(4)
                await self._archive_page_content(
                    page,
                    "ChatGPT",
                    allow_chatgpt_project_capture=bool(folder_name and entry.get("selector_mode")),
                    title_override=title_text,
                )
                if folder_name and entry.get("selector_mode"):
                    await page.goto(project_page_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
            except Exception as exc:
                logging.debug(f"Skipping ChatGPT conversation '{title_text}': {exc}")
                self._record_save_failure(
                    title_text,
                    str(exc),
                    platform="ChatGPT",
                    url=target_url if not entry.get("selector_mode") else page.url,
                    exception_type=type(exc).__name__,
                )

        return len(discovered)

    async def run_archival_sweep(self, platforms=None, target_keyword=None, args_limit=15):
        if not platforms:
            platforms = list(TARGETS.keys())

        self._write_state(
            status="running",
            phase="dispatch",
            detail=f"Targeting {', '.join(platforms)}",
            target_platforms=platforms,
            keyword=target_keyword,
            scan_limit=args_limit,
        )
        logging.info(f"Commencing Great Archivist sweep on targets: {', '.join(platforms)}")

        for key in platforms:
            current_state = self._write_state()
            if current_state.get("status") == "error":
                return
            if key not in TARGETS:
                continue
            target = TARGETS[key]
            name = target["name"]
            url = target["url"]
            email = target.get("email")
            self._write_state(phase="platform", detail=f"Scanning {name}", current_platform=name, current_title=None)

            page = await self.engine.ensure_page(url, wait_sec=5, account_email=email)
            await page.bring_to_front()

            wall_issue = await self.engine.detect_security_wall(page)
            if key == "grok" and not wall_issue and await page.locator('button:has-text("Log in")').count() > 0:
                wall_issue = "Login Required"
            if wall_issue:
                self._trigger_intervention(name, url, wall_issue)
                await self._wait_for_intervention()
                page = await self.engine.ensure_page(url, wait_sec=5, account_email=email)
                continue

            await asyncio.sleep(3)

            if key == "chatgpt":
                await self._collect_chatgpt_history(page, target_keyword, args_limit)
                current_state = self._write_state()
                if current_state.get("status") == "error":
                    return
                continue

            if key in SELECTORS:
                sel = SELECTORS[key]
                sidebar_items = None
                count = 0
                active_selector = sel["list_of_titles"]
                for history_selector in _history_selectors_for_platform(key, sel["list_of_titles"]):
                    try:
                        candidate_items = page.locator(history_selector)
                        candidate_count = await candidate_items.count()
                    except Exception:
                        continue
                    if candidate_count > count:
                        sidebar_items = candidate_items
                        count = candidate_count
                        active_selector = history_selector
                if count > 0:
                    saved_before_platform = len(self.saved_files)
                    try:
                        sweep_limit = int(args_limit)
                    except (ValueError, TypeError):
                        sweep_limit = count if str(args_limit).lower() == "all" else 15
                    actual_limit = min(count, sweep_limit)
                    self._write_state(
                        phase="history_scan",
                        detail=f"{name}: found {count} chats, scanning top {actual_limit}",
                        current_platform=name,
                    )
                    for i in range(actual_limit):
                        item = sidebar_items.nth(i)
                        try:
                            before_url = getattr(page, "url", "")
                            if await item.locator(sel["title_text"]).count() > 0:
                                title_text = await item.locator(sel["title_text"]).first.inner_text()
                            else:
                                title_text = await item.inner_text()
                            title_text = title_text.strip()
                            if not title_text:
                                continue
                            if target_keyword and target_keyword.lower() not in title_text.lower():
                                continue
                            self._write_state(
                                phase="history_item",
                                detail=f"{name}: archiving '{title_text[:90]}'",
                                current_platform=name,
                                current_title=title_text,
                            )
                            await item.click()
                            try:
                                await page.wait_for_url(lambda url: url != before_url, timeout=8000)
                            except Exception:
                                await asyncio.sleep(4)
                            result = await self._archive_page_content(page, name, title_override=title_text)
                            if not result:
                                self._record_save_failure(
                                    title_text,
                                    "History item click completed, but no verified archive file was produced.",
                                    platform=name,
                                    url=getattr(page, "url", ""),
                                )
                        except Exception as exc:
                            logging.debug(f"Skipping unclickable sidebar item: {exc}")
                            self._record_save_failure(
                                title_text if "title_text" in locals() else f"{name} history item {i + 1}",
                                str(exc),
                                platform=name,
                                url=getattr(page, "url", ""),
                                exception_type=type(exc).__name__,
                            )
                    if key == "perplexity" and len(self.saved_files) == saved_before_platform:
                        diagnostics_path = await self._capture_history_diagnostics(page, key, "history_scan_unsaved")
                        self._write_state(
                            status="error",
                            phase="history_unsaved",
                            detail=f"{name} exposed history candidates, but none produced verified archive files. Diagnostics: {diagnostics_path}",
                            current_platform=name,
                        )
                        return
                else:
                    diagnostics_path = await self._capture_history_diagnostics(page, key, "history_empty")
                    self._write_state(
                        status="error",
                        phase="history_empty",
                        detail=f"{name} did not expose any verified history entries. Archive aborted to avoid saving the provider homepage. Diagnostics: {diagnostics_path}",
                        current_platform=name,
                    )
                    return

            if key != "perplexity" and not self.saved_files:
                await self._archive_page_content(page, name)

        if not self.saved_files:
            failure_tail = ""
            if self.save_failures:
                latest_failure = self.save_failures[-1]
                latest_reason = latest_failure.get("reason") or "Unknown save failure."
                failure_tail = f" Latest save failure: {latest_reason}"
            self._write_state(
                status="error",
                phase="no_content",
                detail=f"Archive Intel did not save any verified chat sessions. No summary was generated.{failure_tail}",
            )
            return
        self._write_state(status="running", phase="synthesis", detail="Preparing Sloane archive summary...")

    def build_summary_report(self, platforms, target_keyword=None, args_limit=15):
        summary_path = os.path.join(self.run_dir, "archive_summary.md")
        preview_sections = []
        for file_path in self.saved_files[:12]:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read(2400)
                preview_sections.append(f"[FILE]\n{file_path}\n\n{content}")
            except Exception:
                continue
        archive_context = "\n\n".join(preview_sections) if preview_sections else "No archived conversation bodies were available."
        operator_prompt = (self.request_data.get("prompt") or "").strip()
        attachment_notes = []
        for attachment in (self.request_data.get("attachments") or [])[:6]:
            preview = (attachment.get("preview") or "").strip()
            attachment_notes.append(f"- {attachment.get('name', 'attachment')}")
            if preview:
                attachment_notes.append(f"  Preview: {preview[:900]}")
        attachment_block = "\n".join(attachment_notes).strip() or "No uploaded files were attached."
        prompt = (
            "You are Sloane, Chief of Staff. Review the archived AI chat sessions below and write a concise executive archive brief.\n\n"
            f"Platforms: {', '.join(platforms)}\n"
            f"Keyword filter: {target_keyword or 'none'}\n"
            f"Requested ChatGPT folder: {self.request_spec.get('folder_name') or 'none'}\n"
            f"Scan limit: {args_limit}\n"
            f"Saved files: {len(self.saved_files)}\n\n"
            f"Founder request: {operator_prompt or 'No additional operator prompt was supplied.'}\n\n"
            f"Attached supporting files:\n{attachment_block}\n\n"
            "Return exactly these sections:\n"
            "Executive Summary:\n"
            "What Was Archived:\n"
            "Patterns Worth Noting:\n"
            "Follow-Up Moves:\n\n"
            f"{archive_context}"
        )
        response = generate_sloane_response(
            base_persona="You are Sloane, Chief of Staff to the Founder at AI Fusion Labs.",
            chat_history=[{"role": "user", "content": prompt}],
            grounding_block="",
            target_name="Sloane",
        )
        brief = response.get("text") or "No summary returned."
        with open(summary_path, "w", encoding="utf-8") as fh:
            fh.write("# Archive Intel Summary\n\n")
            fh.write(f"**Run ID:** {self.run_id}\n")
            fh.write(f"**Generated:** {datetime.now().isoformat()}\n")
            fh.write(f"**Platforms:** {', '.join(platforms)}\n")
            fh.write(f"**Saved Files:** {len(self.saved_files)}\n\n")
            fh.write(brief)
            fh.write("\n\n## Archived Files\n")
            for file_path in self.saved_files:
                fh.write(f"- {file_path}\n")
        self._write_state(summary_path=summary_path, detail="Sloane summary written.")
        return summary_path, brief

    def dispatch_summary_email(self, summary_path, brief):
        if not self.email_recipient:
            return {"success": False, "reason": "no_recipient"}
        try:
            subject = f"Archive Intel Summary | {self.run_id}"
            body = (
                "Rob,\n\n"
                "The Archive Intel sweep is complete. Sloane's summary is attached.\n\n"
                f"{brief}\n\n"
                "Sloane"
            )
            result = dispatch_report_email(subject, body, self.email_recipient, attachments=[summary_path])
            self._write_state(email_sent=bool(result.get("success")), detail=f"Email dispatch {'succeeded' if result.get('success') else 'failed'}.")
            return result
        except Exception as exc:
            self._write_state(email_sent=False, detail=f"Email dispatch failed: {exc}")
            return {"success": False, "error": str(exc)}

    async def run_heartbeat_janitor(self):
        logging.info("Starting Heartbeat Janitor (Ctrl+C to stop)...")
        while True:
            for target in TARGETS.values():
                try:
                    page = await self.engine.ensure_page(target["url"], wait_sec=2, account_email=target.get("email"))
                    await page.evaluate("window.scrollBy(0, 50)")
                except Exception as exc:
                    logging.warning(f"Heartbeat ping failed for {target['name']}: {exc}")
            await asyncio.sleep(45 * 60)


async def main():
    parser = argparse.ArgumentParser(description="The Great Archivist")
    parser.add_argument("--platform", type=str, help="Specific platform to archive (chatgpt, perplexity, gemini, grok)")
    parser.add_argument("--keyword", type=str, help="Only archive conversations matching this keyword in title")
    parser.add_argument("--limit", type=str, default="15", help="Number of sidebar items to scan, or 'all'")
    parser.add_argument("--heartbeat", action="store_true", help="Run the continuous Heartbeat Janitor loop")
    parser.add_argument("--run-id", type=str, help="Run identifier for Hub status tracking")
    parser.add_argument("--email", type=str, help="Optional summary email recipient")
    args = parser.parse_args()

    archivist = LLMArchivist(run_id=args.run_id, email_recipient=args.email)
    if not await archivist.connect():
        archivist._write_state(status="error", phase="connect_failed", detail="Browser connection failed.")
        return

    try:
        if args.heartbeat:
            await archivist.run_heartbeat_janitor()
        else:
            platforms = [args.platform.lower()] if args.platform else None
            await archivist.run_archival_sweep(platforms, args.keyword, args.limit)
            current_state = archivist._write_state()
            if current_state.get("status") == "error":
                return
            selected_platforms = platforms or list(TARGETS.keys())
            summary_path, brief = archivist.build_summary_report(selected_platforms, args.keyword, args.limit)
            email_result = archivist.dispatch_summary_email(summary_path, brief)
            final_detail = "Archive Intel sweep completed."
            if args.email and not email_result.get("success"):
                final_detail = "Archive Intel completed, but the summary email failed."
            archivist._write_state(
                status="completed",
                phase="completed",
                detail=final_detail,
                summary_path=summary_path,
                email_result=email_result,
            )
    except Exception as exc:
        archivist._write_state(status="error", phase="failed", detail=str(exc))
        raise
    finally:
        if not args.heartbeat:
            await archivist.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
