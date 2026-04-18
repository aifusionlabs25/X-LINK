import sys
import types
import json
import asyncio
from pathlib import Path


fake_async_api = types.ModuleType("playwright.async_api")
fake_async_api.async_playwright = lambda: None
fake_async_api.Page = object
sys.modules.setdefault("playwright", types.ModuleType("playwright"))
sys.modules["playwright.async_api"] = fake_async_api
fake_stealth = types.ModuleType("playwright_stealth")
fake_stealth.Stealth = type("Stealth", (), {})
sys.modules["playwright_stealth"] = fake_stealth

from tools.great_archivist import (
    LLMArchivist,
    _chatgpt_conversation_selectors,
    _extract_archive_folder,
    _is_chatgpt_conversation_url,
    _is_probably_chatgpt_noise,
    _looks_like_chatgpt_project_row,
    _should_abort_folder_scoped_collection,
)


def test_extract_archive_folder_from_prompt_quotes():
    prompt = 'pull the last 10 ChatGPT chats from "X Agents" and produce an executive digest'
    assert _extract_archive_folder(prompt) == "X Agents"


def test_extract_archive_folder_from_named_folder_prompt():
    prompt = "use only the Projects, folder named 'X Agents'. You may have to scroll down to locate the correct folder."
    assert _extract_archive_folder(prompt) == "X Agents"


def test_chatgpt_conversation_url_filter_accepts_real_threads():
    assert _is_chatgpt_conversation_url("https://chatgpt.com/c/abc123-def456")
    assert not _is_chatgpt_conversation_url("https://chatgpt.com/library")


def test_chatgpt_noise_filter_rejects_library_and_apps_pages():
    assert _is_probably_chatgpt_noise("ChatGPT - Library", "https://chatgpt.com/library")
    assert _is_probably_chatgpt_noise(
        "ChatGPT Apps Browse and chat with your favorite assistants",
        "https://chatgpt.com/gpts",
    )
    assert not _is_probably_chatgpt_noise(
        "Customer onboarding cleanup",
        "https://chatgpt.com/c/abc123-def456",
    )
    assert not _is_probably_chatgpt_noise(
        "Project chat row",
        "https://chatgpt.com/g/g-p-6817f8f87908819196d7a16759cb96b9-x-agents/c/69855246-9b1c-8329-94ab-5a9714865b6a",
    )


def test_chatgpt_folder_collection_prefers_main_project_list():
    selectors = _chatgpt_conversation_selectors("X Agents")
    assert selectors[0] == 'main a[href*="/c/"]'
    assert 'nav[aria-label="Chat history"] a[href*="/c/"]' not in selectors


def test_chatgpt_project_row_filter_accepts_project_chats_and_rejects_controls():
    assert _looks_like_chatgpt_project_row("Branch · Clio SaaS API Overview Apr 7")
    assert _looks_like_chatgpt_project_row("Catch-up with Nova make a one page cheat for each scenario Apr 6")
    assert not _looks_like_chatgpt_project_row("Show project details")
    assert not _looks_like_chatgpt_project_row("Open project options for X Agents")


def test_folder_scoped_collection_aborts_when_folder_not_verified():
    assert _should_abort_folder_scoped_collection("X Agents", focused=False, verified=False, discovered_count=10)
    assert _should_abort_folder_scoped_collection("X Agents", focused=True, verified=False, discovered_count=10)
    assert _should_abort_folder_scoped_collection("X Agents", focused=True, verified=True, discovered_count=0)
    assert not _should_abort_folder_scoped_collection("X Agents", focused=True, verified=True, discovered_count=5)


def test_run_archival_sweep_sets_error_when_no_verified_content(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_empty")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []

    async def fake_collect(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(archivist, "_collect_chatgpt_history", fake_collect)

    class FakePage:
        async def bring_to_front(self):
            return None

        def locator(self, *_args, **_kwargs):
            class Dummy:
                async def count(self):
                    return 0
            return Dummy()

    class FakeEngine:
        async def ensure_page(self, *_args, **_kwargs):
            return FakePage()

        async def detect_security_wall(self, *_args, **_kwargs):
            return None

    archivist.engine = FakeEngine()

    states = []

    def capture_state(**updates):
        if updates:
            states.append(updates)
            return updates
        return {"status": states[-1].get("status", "running")} if states else {"status": "running"}

    monkeypatch.setattr(archivist, "_write_state", capture_state)

    asyncio.run(archivist.run_archival_sweep(["chatgpt"], None, 10))

    assert any(state.get("phase") == "no_content" and state.get("status") == "error" for state in states)


def test_run_archival_sweep_surfaces_latest_save_failure_in_no_content_state(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_failure_tail")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []
    archivist.save_failures = [{"reason": "Row click timed out before navigation."}]

    async def fake_collect(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(archivist, "_collect_chatgpt_history", fake_collect)

    class FakePage:
        async def bring_to_front(self):
            return None

        def locator(self, *_args, **_kwargs):
            class Dummy:
                async def count(self):
                    return 0
            return Dummy()

    class FakeEngine:
        async def ensure_page(self, *_args, **_kwargs):
            return FakePage()

        async def detect_security_wall(self, *_args, **_kwargs):
            return None

    archivist.engine = FakeEngine()

    states = []

    def capture_state(**updates):
        if updates:
            states.append(updates)
            return updates
        return {"status": states[-1].get("status", "running")} if states else {"status": "running"}

    monkeypatch.setattr(archivist, "_write_state", capture_state)

    asyncio.run(archivist.run_archival_sweep(["chatgpt"], None, 10))

    assert any("Latest save failure: Row click timed out before navigation." in state.get("detail", "") for state in states)


def test_capture_chatgpt_folder_diagnostics_writes_candidate_report(tmp_path):
    archivist = LLMArchivist(run_id="archive_test_diag")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")

    class FakePage:
        url = "https://chatgpt.com"

        async def title(self):
            return "ChatGPT"

        async def evaluate(self, *_args, **_kwargs):
            return {
                "visible_sidebar_candidates": ["Projects", "X Agents", "New chat"],
                "matching_folder_text": ["X Agents"],
                "project_related_text": ["Projects"],
            }

    diagnostics_path = asyncio.run(
        archivist._capture_chatgpt_folder_diagnostics(
            FakePage(),
            "X Agents",
            "folder_unverified",
        )
    )

    with open(diagnostics_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    assert payload["folder_name"] == "X Agents"
    assert payload["reason"] == "folder_unverified"
    assert "X Agents" in payload["matching_folder_text"]


def test_archive_page_content_allows_chatgpt_project_capture(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_project_capture")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []
    Path(archivist.run_dir).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("tools.great_archivist.VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setattr("tools.great_archivist.ARCHIVAL_PARAMS", {"projects": [], "ignore_titles": []})
    monkeypatch.setattr("tools.great_archivist.SELECTORS", {})
    monkeypatch.setattr(archivist, "_write_state", lambda **updates: updates or {"status": "running"})

    class FakePage:
        url = "https://chatgpt.com/g/g-p-123/project"

        async def title(self):
            return "ChatGPT - X Agents"

        async def inner_text(self, _selector):
            return "Project conversation body"

    result = asyncio.run(
        archivist._archive_page_content(
            FakePage(),
            "ChatGPT",
            allow_chatgpt_project_capture=True,
            title_override="Branch · Clio SaaS API Overview Apr 7",
        )
    )

    assert result is not None
    assert Path(result).exists()


def test_archive_page_content_synthesizes_project_capture_when_page_text_is_unavailable(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_project_fallback")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []
    Path(archivist.run_dir).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("tools.great_archivist.VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setattr("tools.great_archivist.ARCHIVAL_PARAMS", {"projects": [], "ignore_titles": []})
    monkeypatch.setattr("tools.great_archivist.SELECTORS", {})
    monkeypatch.setattr(archivist, "_write_state", lambda **updates: updates or {"status": "running"})

    class FakePage:
        url = "https://chatgpt.com/g/g-p-123/project"

        async def title(self):
            return "ChatGPT - X Agents"

        async def inner_text(self, _selector):
            raise RuntimeError("no readable text")

        async def content(self):
            raise RuntimeError("no html content")

    result = asyncio.run(
        archivist._archive_page_content(
            FakePage(),
            "ChatGPT",
            allow_chatgpt_project_capture=True,
            title_override="Branch Â· Project fallback",
        )
    )

    assert result is not None
    saved = Path(result).read_text(encoding="utf-8")
    assert "Project-scoped ChatGPT capture" in saved


def test_chatgpt_history_uses_discovered_title_for_non_selector_entries(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_title_override")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []
    archivist.request_spec["folder_name"] = ""

    captured_titles = []

    async def fake_archive_page_content(_page, _platform, **kwargs):
        captured_titles.append(kwargs.get("title_override"))
        return "ok"

    monkeypatch.setattr(archivist, "_archive_page_content", fake_archive_page_content)
    monkeypatch.setattr(archivist, "_write_state", lambda **updates: updates or {"status": "running"})

    class FakeItem:
        def __init__(self, href, text):
            self.href = href
            self.text = text

        async def get_attribute(self, name):
            return self.href if name == "href" else None

        async def inner_text(self):
            return self.text

    class FakeLocator:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class FakePage:
        url = "https://chatgpt.com"

        def locator(self, selector):
            if selector == 'nav[aria-label="Chat history"] a[href*="/c/"]':
                return FakeLocator([FakeItem("/c/abc123", "Amy to Taylor debranding")])
            return FakeLocator([])

        async def goto(self, *_args, **_kwargs):
            return None

    count = asyncio.run(archivist._collect_chatgpt_history(FakePage(), None, 10))

    assert count == 1
    assert captured_titles == ["Amy to Taylor debranding"]


def test_generic_history_uses_sidebar_title_and_skips_fallback_when_items_saved(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_generic_titles")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []

    captured_titles = []

    async def fake_archive_page_content(_page, _platform, **kwargs):
        captured_titles.append(kwargs.get("title_override"))
        archivist.saved_files.append(f"saved-{len(captured_titles)}.md")
        return "ok"

    monkeypatch.setattr(archivist, "_archive_page_content", fake_archive_page_content)
    monkeypatch.setattr(archivist, "_write_state", lambda **updates: updates or {"status": "running"})

    class FakeTitleLocator:
        def __init__(self, text):
            self.text = text

        async def count(self):
            return 1

        @property
        def first(self):
            return self

        async def inner_text(self):
            return self.text

    class FakeItem:
        def __init__(self, text):
            self.text = text

        def locator(self, _selector):
            return FakeTitleLocator(self.text)

        async def inner_text(self):
            return self.text

        async def click(self):
            return None

    class FakeSidebarLocator:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class FakePage:
        def locator(self, selector):
            if selector == "a[href^='/search/']":
                return FakeSidebarLocator([FakeItem("Perplexity Topic One"), FakeItem("Perplexity Topic Two")])
            raise AssertionError(f"Unexpected selector: {selector}")

        async def bring_to_front(self):
            return None

    class FakeEngine:
        async def ensure_page(self, *_args, **_kwargs):
            return FakePage()

        async def detect_security_wall(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("tools.great_archivist.SELECTORS", {
        "perplexity": {
            "list_of_titles": "a[href^='/search/']",
            "title_text": "a[href^='/search/'] span",
            "message_containers": ".scrollable-container .group",
            "user_message_text": "h1",
            "ai_message_text": ".prose",
        }
    })

    archivist.engine = FakeEngine()

    asyncio.run(archivist.run_archival_sweep(["perplexity"], None, 2))

    assert captured_titles == ["Perplexity Topic One", "Perplexity Topic Two"]


def test_perplexity_history_fails_closed_when_no_history_entries_are_visible(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_perplexity_empty")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []

    diagnostics = []
    states = []

    async def fake_capture_history_diagnostics(_page, platform_key, reason):
        diagnostics.append((platform_key, reason))
        return str(tmp_path / "run" / "perplexity_history_diagnostics.json")

    monkeypatch.setattr(archivist, "_capture_history_diagnostics", fake_capture_history_diagnostics)

    def capture_state(**updates):
        if updates:
            states.append(updates)
            return updates
        return {"status": states[-1].get("status", "running")} if states else {"status": "running"}

    monkeypatch.setattr(archivist, "_write_state", capture_state)

    class EmptyLocator:
        async def count(self):
            return 0

        def nth(self, _index):
            raise AssertionError("Should not request nth item when no history exists")

    class FakePage:
        def locator(self, _selector):
            return EmptyLocator()

        async def bring_to_front(self):
            return None

    class FakeEngine:
        async def ensure_page(self, *_args, **_kwargs):
            return FakePage()

        async def detect_security_wall(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("tools.great_archivist.SELECTORS", {
        "perplexity": {
            "list_of_titles": "a[href^='/search/']",
            "title_text": "a[href^='/search/'] span",
            "message_containers": ".scrollable-container .group",
            "user_message_text": "h1",
            "ai_message_text": ".prose",
        }
    })

    archivist.engine = FakeEngine()

    asyncio.run(archivist.run_archival_sweep(["perplexity"], None, 2))

    assert diagnostics == [("perplexity", "history_empty")]
    assert any(state.get("phase") == "history_empty" and state.get("status") == "error" for state in states)


def test_perplexity_history_fails_closed_when_candidates_produce_no_saved_files(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_perplexity_unsaved")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []

    diagnostics = []
    states = []

    async def fake_capture_history_diagnostics(_page, platform_key, reason):
        diagnostics.append((platform_key, reason))
        return str(tmp_path / "run" / "perplexity_history_diagnostics.json")

    async def fake_archive_page_content(_page, _platform, **_kwargs):
        return None

    monkeypatch.setattr(archivist, "_capture_history_diagnostics", fake_capture_history_diagnostics)
    monkeypatch.setattr(archivist, "_archive_page_content", fake_archive_page_content)

    def capture_state(**updates):
        if updates:
            states.append(updates)
            return updates
        return {"status": states[-1].get("status", "running")} if states else {"status": "running"}

    monkeypatch.setattr(archivist, "_write_state", capture_state)

    class FakeTitleLocator:
        def __init__(self, text):
            self.text = text

        async def count(self):
            return 1

        @property
        def first(self):
            return self

        async def inner_text(self):
            return self.text

    class FakeItem:
        def __init__(self, text):
            self.text = text

        def locator(self, _selector):
            return FakeTitleLocator(self.text)

        async def inner_text(self):
            return self.text

        async def click(self):
            return None

    class FakeSidebarLocator:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class FakePage:
        def locator(self, selector):
            if selector in {"a[href^='/search/']", "aside a[href*='/search/']", "nav a[href*='/search/']"}:
                return FakeSidebarLocator([FakeItem("Perplexity Topic One")])
            return FakeSidebarLocator([])

        async def bring_to_front(self):
            return None

    class FakeEngine:
        async def ensure_page(self, *_args, **_kwargs):
            return FakePage()

        async def detect_security_wall(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("tools.great_archivist.SELECTORS", {
        "perplexity": {
            "list_of_titles": "a[href^='/search/']",
            "title_text": "a[href^='/search/'] span",
            "message_containers": ".scrollable-container .group",
            "user_message_text": "h1",
            "ai_message_text": ".prose",
        }
    })

    archivist.engine = FakeEngine()

    asyncio.run(archivist.run_archival_sweep(["perplexity"], None, 1))

    assert diagnostics == [("perplexity", "history_scan_unsaved")]
    assert any(state.get("phase") == "history_unsaved" and state.get("status") == "error" for state in states)


def test_generic_history_records_save_failures_when_clicks_produce_no_archive(monkeypatch, tmp_path):
    archivist = LLMArchivist(run_id="archive_test_generic_unsaved_detail")
    archivist.run_dir = str(tmp_path / "run")
    archivist.state_path = str(tmp_path / "run" / "state.json")
    archivist.request_path = str(tmp_path / "run" / "request.json")
    archivist.saved_files = []

    async def fake_capture_history_diagnostics(_page, platform_key, reason):
        return str(tmp_path / "run" / f"{platform_key}_{reason}.json")

    async def fake_archive_page_content(_page, _platform, **_kwargs):
        return None

    monkeypatch.setattr(archivist, "_capture_history_diagnostics", fake_capture_history_diagnostics)
    monkeypatch.setattr(archivist, "_archive_page_content", fake_archive_page_content)
    monkeypatch.setattr(archivist, "_write_state", lambda **updates: updates or {"status": "running"})

    class FakeTitleLocator:
        def __init__(self, text):
            self.text = text

        async def count(self):
            return 1

        @property
        def first(self):
            return self

        async def inner_text(self):
            return self.text

    class FakeItem:
        def __init__(self, text):
            self.text = text

        def locator(self, _selector):
            return FakeTitleLocator(self.text)

        async def inner_text(self):
            return self.text

        async def click(self):
            return None

    class FakeSidebarLocator:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class FakePage:
        url = "https://www.perplexity.ai/"

        def locator(self, selector):
            if selector in {"a[href^='/search/']", "aside a[href*='/search/']", "nav a[href*='/search/']"}:
                return FakeSidebarLocator([FakeItem("Perplexity Topic One")])
            return FakeSidebarLocator([])

        async def bring_to_front(self):
            return None

        async def wait_for_url(self, *_args, **_kwargs):
            raise RuntimeError("url did not change")

    class FakeEngine:
        async def ensure_page(self, *_args, **_kwargs):
            return FakePage()

        async def detect_security_wall(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("tools.great_archivist.SELECTORS", {
        "perplexity": {
            "list_of_titles": "a[href^='/search/']",
            "title_text": "a[href^='/search/'] span",
            "message_containers": ".scrollable-container .group",
            "user_message_text": "h1",
            "ai_message_text": ".prose",
        }
    })

    archivist.engine = FakeEngine()

    asyncio.run(archivist.run_archival_sweep(["perplexity"], None, 1))

    assert archivist.save_failures
    assert archivist.save_failures[-1]["reason"] == "History item click completed, but no verified archive file was produced."
