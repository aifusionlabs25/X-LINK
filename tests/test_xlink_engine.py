import asyncio
import sys
import types


def test_xlink_engine_falls_back_to_managed_browser(monkeypatch):
    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: None
    fake_async_api.Page = object
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    fake_stealth = types.ModuleType("playwright_stealth")
    fake_stealth.Stealth = type("Stealth", (), {})
    monkeypatch.setitem(sys.modules, "playwright_stealth", fake_stealth)

    import x_link_engine as engine_mod
    from x_link_engine import XLinkEngine

    class FakeBrowser:
        contexts = []

    class FakeContext:
        browser = FakeBrowser()

        async def close(self):
            return None

    class FakeChromium:
        async def connect_over_cdp(self, url):
            raise RuntimeError("cdp unavailable")

        async def launch_persistent_context(self, **kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            return None

    class FakePlaywrightManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(engine_mod, "async_playwright", lambda: FakePlaywrightManager())

    engine = XLinkEngine()
    connected = asyncio.run(engine.connect())

    assert connected is True
    assert engine.context is not None
    assert engine.owns_browser is True


def test_ensure_page_can_stay_on_preferred_background_page(monkeypatch):
    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: None
    fake_async_api.Page = object
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    fake_stealth = types.ModuleType("playwright_stealth")
    fake_stealth.Stealth = type("Stealth", (), {})
    monkeypatch.setitem(sys.modules, "playwright_stealth", fake_stealth)

    import x_link_engine as engine_mod
    from x_link_engine import XLinkEngine

    class FakeStealth:
        async def apply_stealth_async(self, page):
            return None

    class FakePage:
        def __init__(self):
            self.url = "about:blank"
            self.goto_calls = []
            self.bring_to_front_calls = 0

        def is_closed(self):
            return False

        async def goto(self, url, wait_until=None, timeout=None):
            self.goto_calls.append(url)
            self.url = url

        async def bring_to_front(self):
            self.bring_to_front_calls += 1

    class FakeContext:
        def __init__(self):
            self.pages = []

        async def new_page(self):
            page = FakePage()
            self.pages.append(page)
            return page

    monkeypatch.setattr(engine_mod, "Stealth", FakeStealth)

    engine = XLinkEngine()
    engine.context = FakeContext()
    preferred_page = FakePage()
    engine.context.pages.append(preferred_page)
    engine.detect_security_wall = types.MethodType(lambda self, page: asyncio.sleep(0), engine)
    engine.verify_gsuite_session = types.MethodType(lambda self, page, email: asyncio.sleep(0, result=True), engine)

    page = asyncio.run(
        engine.ensure_page(
            "https://mail.google.com/mail/u/novaaifusionlabs@gmail.com/#inbox",
            wait_sec=0,
            bring_to_front=False,
            account_email="novaaifusionlabs@gmail.com",
            preferred_page=preferred_page,
            reuse_existing=False,
        )
    )

    assert page is preferred_page
    assert preferred_page.goto_calls
    assert preferred_page.bring_to_front_calls == 0
