import asyncio
import sys
import types


class _FakeKeyboard:
    def __init__(self):
        self.presses = []

    async def press(self, key):
        self.presses.append(key)


class _FakeLocator:
    def __init__(self, selector):
        self.selector = selector
        self.filled = None
        self.files = None

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    async def wait_for(self, state=None, timeout=None):
        return None

    async def click(self):
        return None

    async def fill(self, value):
        self.filled = value

    async def set_input_files(self, files):
        self.files = files


class _FakePage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()
        self.closed = False
        self.locators = {}
        self.goto_calls = []

    def locator(self, selector):
        locator = self.locators.get(selector)
        if locator is None:
            locator = _FakeLocator(selector)
            self.locators[selector] = locator
        return locator

    def is_closed(self):
        return self.closed

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})

    async def close(self):
        self.closed = True


class _FakeEngine:
    def __init__(self, page):
        self.page = page
        self.ensure_kwargs = None

    async def connect(self):
        return True

    async def ensure_page(self, url, **kwargs):
        self.ensure_kwargs = {"url": url, **kwargs}
        return self.page

    async def human_type(self, page, selector, text):
        return None

    async def human_click(self, page, selector):
        return None


def test_gmail_send_uses_throwaway_tab_and_closes_it(tmp_path):
    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: None
    fake_async_api.Page = object
    sys.modules.setdefault("playwright", types.ModuleType("playwright"))
    sys.modules["playwright.async_api"] = fake_async_api
    fake_stealth = types.ModuleType("playwright_stealth")
    fake_stealth.Stealth = type("Stealth", (), {})
    sys.modules["playwright_stealth"] = fake_stealth

    from tools.gsuite_handler import GSuiteHandler

    attachment = tmp_path / "overview.png"
    attachment.write_bytes(b"png")

    page = _FakePage()
    engine = _FakeEngine(page)
    handler = GSuiteHandler()
    handler.engine = engine

    result = asyncio.run(
        handler.gmail_send(
            "aifusionlabs@gmail.com",
            "Subject",
            "Body",
            attachments=[str(attachment)],
        )
    )

    assert "successfully" in result.lower()
    assert engine.ensure_kwargs["reuse_existing"] is True
    assert engine.ensure_kwargs["url"].endswith("/#inbox")
    assert page.closed is True
    send_locator = page.locators['div[role="button"][data-tooltip^="Send"]']
    assert send_locator is not None
    assert page.keyboard.presses.count("Control+Enter") in {0, 1}


def test_gmail_list_uses_atom_feed_and_closes_tab(monkeypatch):
    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: None
    fake_async_api.Page = object
    sys.modules.setdefault("playwright", types.ModuleType("playwright"))
    sys.modules["playwright.async_api"] = fake_async_api
    fake_stealth = types.ModuleType("playwright_stealth")
    fake_stealth.Stealth = type("Stealth", (), {})
    sys.modules["playwright_stealth"] = fake_stealth

    from tools.gsuite_handler import GSuiteHandler

    class FakeContext:
        async def cookies(self, urls):
            return [{"name": "SID", "value": "cookie", "domain": ".google.com", "path": "/"}]

    class FakeSession:
        def __init__(self):
            self.cookies = types.SimpleNamespace(set=lambda *args, **kwargs: None)

        def get(self, url, timeout=20):
            class Response:
                text = """<?xml version='1.0' encoding='UTF-8'?>
                <feed xmlns='http://purl.org/atom/ns#'>
                  <entry>
                    <title>Founder note</title>
                    <summary>Please review the latest mission.</summary>
                    <issued>2026-04-11T10:00:00Z</issued>
                    <author><email>aifusionlabs@gmail.com</email></author>
                  </entry>
                </feed>"""

                def raise_for_status(self):
                    return None

            return Response()

    page = _FakePage()
    engine = _FakeEngine(page)
    engine.context = FakeContext()
    handler = GSuiteHandler()
    handler.engine = engine

    monkeypatch.setattr("tools.gsuite_handler.requests.Session", FakeSession)

    result = asyncio.run(handler.gmail_list(limit=3))

    assert result["success"] is True
    assert result["count"] == 1
    assert result["entries"][0]["subject"] == "Founder note"
    assert engine.ensure_kwargs["reuse_existing"] is True
    assert page.closed is True


def test_gmail_read_latest_falls_back_to_atom_feed(monkeypatch):
    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: None
    fake_async_api.Page = object
    sys.modules.setdefault("playwright", types.ModuleType("playwright"))
    sys.modules["playwright.async_api"] = fake_async_api
    fake_stealth = types.ModuleType("playwright_stealth")
    fake_stealth.Stealth = type("Stealth", (), {})
    sys.modules["playwright_stealth"] = fake_stealth

    from tools.gsuite_handler import GSuiteHandler

    class FakeContext:
        async def cookies(self, urls):
            return [{"name": "SID", "value": "cookie", "domain": ".google.com", "path": "/"}]

    class FailingLocator(_FakeLocator):
        async def wait_for(self, state=None, timeout=None):
            raise RuntimeError("locator timeout")

    class FakeReadPage(_FakePage):
        def locator(self, selector):
            locator = self.locators.get(selector)
            if locator is None:
                locator = FailingLocator(selector)
                self.locators[selector] = locator
            return locator

    class FakeSession:
        def __init__(self):
            self.cookies = types.SimpleNamespace(set=lambda *args, **kwargs: None)

        def get(self, url, timeout=20):
            class Response:
                text = """<?xml version='1.0' encoding='UTF-8'?>
                <feed xmlns='http://purl.org/atom/ns#'>
                  <entry>
                    <title>Fwd: Your Google Play Order Receipt from Apr 10, 2026</title>
                    <summary>Total charged: $9.99 Order date: Apr 10, 2026</summary>
                    <issued>2026-04-11T10:00:00Z</issued>
                    <author><email>rvicks@gmail.com</email></author>
                  </entry>
                </feed>"""

                def raise_for_status(self):
                    return None

            return Response()

    page = FakeReadPage()
    engine = _FakeEngine(page)
    engine.context = FakeContext()
    handler = GSuiteHandler()
    handler.engine = engine

    monkeypatch.setattr("tools.gsuite_handler.requests.Session", FakeSession)

    result = asyncio.run(
        handler.gmail_read_latest(
            account_email="novaaifusionlabs@gmail.com",
            query="Google Play Order Receipt",
            sender_filter="rvicks@gmail.com",
        )
    )

    assert result["success"] is True
    assert result["source"] == "gmail_atom_feed"
    assert "Total charged: $9.99" in result["body"]
