from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from ai_marketplace_monitor import monitor as monitor_module
from ai_marketplace_monitor.facebook import FacebookMarketplace
from ai_marketplace_monitor.marketplace import Marketplace
from ai_marketplace_monitor.monitor import MarketplaceMonitor
from ai_marketplace_monitor.utils import MonitorConfig


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MarketplaceMonitor:
    monkeypatch.setattr(monitor_module, "sync_playwright", Mock())
    monkeypatch.setattr(monitor_module, "amm_home", tmp_path)
    monkeypatch.setattr(monitor_module, "cache", Mock())
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    instance = MarketplaceMonitor([], headless=False, logger=Mock())
    instance.config = SimpleNamespace(monitor=MonitorConfig(name="monitor"))
    return instance


def test_persistent_chrome_defaults_off() -> None:
    assert MonitorConfig(name="monitor").persistent_chrome is False


@pytest.mark.parametrize("value", ["true", 1, None])
def test_persistent_chrome_requires_boolean(value: object) -> None:
    with pytest.raises(ValueError, match="persistent_chrome must be a boolean"):
        MonitorConfig(name="monitor", persistent_chrome=value)


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit", None])
def test_launch_fallbacks(
    monitor: MarketplaceMonitor, persistent: bool, engine: str | None
) -> None:
    monitor.config.monitor.persistent_chrome = persistent
    monitor.playwright.chromium.launch_persistent_context.side_effect = RuntimeError("locked")
    engines = ("chromium", "firefox", "webkit")
    for name in engines:
        if name != engine:
            getattr(monitor.playwright, name).launch.side_effect = RuntimeError("unavailable")
    if engine is None:
        with pytest.raises(RuntimeError, match="No browser could be launched"):
            monitor._launch_browser()
    else:
        result = monitor._launch_browser()
        assert result is getattr(monitor.playwright, engine).launch.return_value
    last = engines.index(engine) if engine else len(engines) - 1
    for index, name in enumerate(engines):
        launch = getattr(monitor.playwright, name).launch
        if index <= last:
            expected = {"headless": False}
            if name == "chromium":
                expected["channel"] = "chrome"
            launch.assert_called_once_with(**expected)
        else:
            launch.assert_not_called()
    assert monitor.playwright.chromium.launch_persistent_context.call_count == int(persistent)
    assert monitor.persistent_context is None


@pytest.mark.parametrize("local_app_data", [True, False])
def test_persistent_launch_uses_dedicated_profile(
    monitor: MarketplaceMonitor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    local_app_data: bool,
) -> None:
    monitor.config.monitor = MonitorConfig(
        name="monitor", persistent_chrome=True, proxy_server=["http://proxy:8080"]
    )
    if not local_app_data:
        monkeypatch.delenv("LOCALAPPDATA")
    expected = tmp_path / "chrome-profile"
    if local_app_data:
        expected = tmp_path / "AI-Marketplace-Monitor" / "chrome-profile"
    assert monitor._launch_browser() is None
    monitor.playwright.chromium.launch_persistent_context.assert_called_once_with(
        user_data_dir=expected,
        channel="chrome",
        headless=False,
        proxy={"server": "http://proxy:8080"},
    )
    assert expected.is_dir()
    assert (
        monitor.persistent_context
        is monitor.playwright.chromium.launch_persistent_context.return_value
    )
    assert monitor.browser is None
    monitor.playwright.chromium.launch.assert_not_called()
    monitor.playwright.firefox.launch.assert_not_called()
    monitor.playwright.webkit.launch.assert_not_called()


def test_persistent_page_reuse_and_ownership() -> None:
    market = Marketplace("facebook", None)
    context = Mock()
    page = Mock()
    page.is_closed.return_value = False
    context.pages = [page]
    market.set_browser(persistent_context=context)
    assert market.create_page() is page
    market.set_browser(persistent_context=context)
    assert market.create_page(swap_proxy=True) is page
    context.new_page.assert_not_called()
    context.new_context.assert_not_called()
    market.stop()
    page.close.assert_called_once()
    context.close.assert_not_called()
    assert market.persistent_context is None
    assert market.page is None


def test_persistent_context_creates_and_replaces_closed_page() -> None:
    market = Marketplace("facebook", None)
    context = Mock(pages=[])
    market.set_browser(persistent_context=context)
    assert market.create_page() is context.new_page.return_value
    old_page = market.page
    old_page.is_closed.return_value = True
    context.new_page.return_value = Mock()
    assert market.create_page() is context.new_page.return_value
    assert market.page is not old_page
    assert context.new_page.call_count == 2
    context.close.assert_not_called()


def test_fresh_context_rotation_and_cleanup() -> None:
    browser = Mock()
    first, second = Mock(), Mock()
    browser.new_context.side_effect = [first, second]
    market = Marketplace("facebook", browser)
    market.config = SimpleNamespace(
        monitor_config=MonitorConfig(
            name="monitor", proxy_server=["http://one:8080", "http://two:8080"]
        )
    )
    assert market.create_page() is first.new_page.return_value
    market.set_browser(browser)
    first.close.assert_not_called()
    assert market.create_page(swap_proxy=True) is second.new_page.return_value
    first.close.assert_called_once()
    assert browser.new_context.call_count == 2
    market.stop()
    second.close.assert_called_once()
    browser.close.assert_not_called()


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("close_fails", [False, True])
def test_shutdown_closes_owner_before_playwright(
    monitor: MarketplaceMonitor, persistent: bool, close_fails: bool
) -> None:
    events = Mock()
    market = Mock()
    owner = Mock()
    if persistent:
        monitor.persistent_context = owner
    else:
        monitor.browser = owner
    monitor.active_marketplaces["facebook"] = market
    monitor.keyboard_monitor = Mock()
    events.attach_mock(market.stop, "market_stop")
    events.attach_mock(owner.close, "owner_close")
    events.attach_mock(monitor.playwright.stop, "playwright_stop")
    events.attach_mock(monitor.keyboard_monitor.stop, "keyboard_stop")
    events.attach_mock(monitor_module.cache.close, "cache_close")
    if close_fails:
        market.stop.side_effect = RuntimeError("already closed")
        owner.close.side_effect = RuntimeError("already closed")
    monitor.stop_monitor()
    assert events.mock_calls == [
        call.market_stop(),
        call.owner_close(),
        call.playwright_stop(),
        call.keyboard_stop(),
        call.cache_close(),
    ]
    assert monitor.browser is None
    assert monitor.persistent_context is None
    assert not monitor.active_marketplaces


def test_monitor_marketplaces_are_not_shared(monitor: MarketplaceMonitor) -> None:
    other = MarketplaceMonitor([], False, None)
    monitor.active_marketplaces["facebook"] = Mock()
    assert not other.active_marketplaces


def test_facebook_login_accepts_context_without_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    market = FacebookMarketplace("facebook", None)
    context = Mock(pages=[])
    market.set_browser(persistent_context=context)
    market.config = SimpleNamespace(username=None, password=None, login_wait_time=0)
    monkeypatch.setattr(market, "goto_url", Mock())
    market.login()
    assert market.page is context.new_page.return_value
    assert market.browser is None


def test_check_items_attaches_existing_persistent_context(
    monitor: MarketplaceMonitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = Mock()
    monitor.persistent_context = context
    config = SimpleNamespace(name="facebook", enabled=True, language=None, notify=[])
    monitor.config.marketplace = {"facebook": config}
    monitor.config.item = {"test": SimpleNamespace(name="test", notify=[])}
    monitor.config.user = {}
    market = Mock()
    listing = SimpleNamespace(name="", title="Test listing")
    market.get_listing_details.return_value = (listing, False)
    monkeypatch.setitem(
        monitor_module.supported_marketplaces, "facebook", Mock(return_value=market)
    )
    monkeypatch.setattr(monitor_module.Listing, "from_cache", Mock(return_value=None))
    for name in ("load_config_file", "load_ai_agents", "_select_translator", "evaluate_by_ai"):
        monkeypatch.setattr(monitor, name, Mock())
    launch = Mock()
    monkeypatch.setattr(monitor, "_launch_browser", launch)
    monitor.check_items(["123", "456"], for_item="test")
    launch.assert_not_called()
    assert market.set_browser.call_args_list == [
        call(None, persistent_context=context),
        call(None, persistent_context=context),
    ]


def test_scheduled_marketplace_receives_persistent_context(
    monitor: MarketplaceMonitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = Mock()
    monitor.persistent_context = context
    monitor.config.marketplace = {
        "facebook": SimpleNamespace(name="facebook", enabled=True, language=None)
    }
    monitor.config.item = {}
    market = Mock()
    monkeypatch.setitem(
        monitor_module.supported_marketplaces, "facebook", Mock(return_value=market)
    )
    for name in ("load_config_file", "load_ai_agents", "_select_translator"):
        monkeypatch.setattr(monitor, name, Mock())
    monitor.schedule_jobs()
    market.set_browser.assert_called_once_with(None, persistent_context=context)
