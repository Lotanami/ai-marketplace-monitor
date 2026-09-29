"""Elapsed timing must not alter retrieval, evaluation, or error handling."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_marketplace_monitor import facebook
from ai_marketplace_monitor.ai import AIResponse
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
)
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.monitor import MarketplaceMonitor


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    value = SimpleNamespace(now=0.0)
    monkeypatch.setattr(facebook.time, "perf_counter", lambda: value.now)
    monkeypatch.setattr(
        facebook.time, "sleep", lambda seconds: setattr(value, "now", value.now + seconds)
    )
    return value


@pytest.fixture
def listing() -> Listing:
    return Listing(
        marketplace="facebook",
        name="test",
        id="1",
        title="Private listing title",
        image="",
        price="100",
        post_url="https://www.facebook.com/marketplace/item/1",
        location="London",
        seller="Private seller",
        condition="Used",
        description="Private body",
    )


@pytest.fixture
def market(monkeypatch: pytest.MonkeyPatch, listing: Listing) -> FacebookMarketplace:
    result = FacebookMarketplace("facebook", None, logger=logging.getLogger("timing-test"))
    result.page = Mock()
    result.configure(FacebookMarketplaceConfig(name="facebook", search_city="london"))
    result.goto_url = Mock()
    monkeypatch.setattr(Listing, "from_cache", Mock(return_value=None))
    monkeypatch.setattr(Listing, "to_cache", Mock())
    monkeypatch.setattr(facebook, "parse_listing", Mock(return_value=listing))
    return result


def timing_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("[Timing]")]


@pytest.mark.parametrize("cached", [False, True])
def test_retrieval_duration_and_cache_behavior(
    market: FacebookMarketplace,
    listing: Listing,
    clock: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    cached: bool,
) -> None:
    caplog.set_level(logging.INFO)
    if cached:
        monkeypatch.setattr(Listing, "from_cache", Mock(return_value=listing))
    market.goto_url.side_effect = lambda url: setattr(clock, "now", clock.now + 8.2)
    result = market.get_listing_details(
        listing.post_url, FacebookItemConfig(name="test", search_phrases="pc")
    )
    assert result == (listing, cached)
    assert market.goto_url.call_count == int(not cached)
    assert timing_messages(caplog) == [
        f"[Timing] Facebook retrieval: {0.0 if cached else 8.2:.1f}s"
    ]


@pytest.mark.parametrize("error", [ValueError("private failure"), KeyboardInterrupt()])
def test_retrieval_exception_is_preserved_and_timed(
    market: FacebookMarketplace,
    listing: Listing,
    clock: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
    error: BaseException,
) -> None:
    caplog.set_level(logging.INFO)

    def fail(url: str) -> None:
        clock.now += 2.0
        raise error

    market.goto_url.side_effect = fail
    with pytest.raises(type(error)) as caught:
        market.get_listing_details(
            listing.post_url, FacebookItemConfig(name="test", search_phrases="pc")
        )
    assert caught.value is error
    assert timing_messages(caplog) == ["[Timing] Facebook retrieval: 2.0s"]


@pytest.mark.parametrize("outcome", ["success", "fallback", "interrupt", "failed"])
def test_ai_duration_preserves_dispatch_and_failures(
    listing: Listing,
    clock: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
    outcome: str,
) -> None:
    caplog.set_level(logging.INFO)
    instance = MarketplaceMonitor.__new__(MarketplaceMonitor)
    instance.logger = logging.getLogger("timing-test")
    response = AIResponse(4, "Good value", name="nvidia")
    interruption = KeyboardInterrupt()

    def evaluate(*args: object, **kwargs: object) -> AIResponse:
        clock.now += 14.7
        if outcome == "interrupt":
            raise interruption
        if outcome in ("fallback", "failed"):
            raise ValueError("existing evaluation failure")
        return response

    first = SimpleNamespace(
        config=SimpleNamespace(name="nvidia"), evaluate=Mock(side_effect=evaluate)
    )
    second = SimpleNamespace(
        config=SimpleNamespace(name="other"), evaluate=Mock(return_value=response)
    )
    instance.ai_agents = [first, second]
    item = FacebookItemConfig(
        name="test",
        search_phrases="pc",
        ai=["nvidia", "other"] if outcome == "fallback" else ["nvidia"],
    )
    config = FacebookMarketplaceConfig(name="facebook")
    if outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt) as caught:
            instance.evaluate_by_ai(listing, item, config)
        assert caught.value is interruption
    else:
        result = instance.evaluate_by_ai(listing, item, config)
        if outcome == "failed":
            assert result.comment == AIResponse.NOT_EVALUATED
        else:
            assert result is response
    assert second.evaluate.call_count == int(outcome == "fallback")
    assert timing_messages(caplog) == ["[Timing] AI inference: 14.7s"]


def test_search_total_includes_consumer_work_but_not_shared_search(
    market: FacebookMarketplace,
    listing: Listing,
    clock: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    market.goto_url.side_effect = lambda url: setattr(clock, "now", clock.now + 8.2)
    monkeypatch.setattr(market, "check_listing", Mock(return_value=True))
    page = Mock()
    page.get_listings.return_value = [listing]
    monkeypatch.setattr(facebook, "FacebookSearchResultPage", Mock(return_value=page))
    results = market.search(FacebookItemConfig(name="test", search_phrases="pc"))
    assert next(results) is listing
    assert timing_messages(caplog) == ["[Timing] Facebook retrieval: 8.2s"]
    clock.now += 14.7
    with pytest.raises(StopIteration):
        next(results)
    assert timing_messages(caplog) == [
        "[Timing] Facebook retrieval: 8.2s",
        "[Timing] Total listing processing: 27.9s",
    ]


def test_check_total_includes_retrieval_and_evaluation(
    market: FacebookMarketplace,
    listing: Listing,
    clock: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    instance = MarketplaceMonitor.__new__(MarketplaceMonitor)
    instance.logger = logging.getLogger("timing-test")
    instance.browser = Mock()
    instance.persistent_context = None
    instance.active_marketplaces = {"facebook": market}
    item = FacebookItemConfig(name="test", search_phrases="pc", ai=["nvidia"])
    instance.config = SimpleNamespace(
        marketplace={"facebook": market.config},
        item={"test": item},
        user={},
    )
    market.set_browser = Mock()
    market.check_listing = Mock(return_value=True)
    market.goto_url.side_effect = lambda url: setattr(clock, "now", clock.now + 8.2)
    for name in ("load_config_file", "load_ai_agents", "_select_translator"):
        monkeypatch.setattr(instance, name, Mock())

    def evaluate(*args: object, **kwargs: object) -> AIResponse:
        clock.now += 14.7
        return AIResponse(4, "Good value", name="nvidia")

    instance.ai_agents = [
        SimpleNamespace(config=SimpleNamespace(name="nvidia"), evaluate=evaluate)
    ]
    instance.check_items([listing.post_url], for_item="test")
    assert timing_messages(caplog) == [
        "[Timing] Facebook retrieval: 8.2s",
        "[Timing] AI inference: 14.7s",
        "[Timing] Total listing processing: 22.9s",
    ]


def test_logging_disabled_keeps_retrieval_result(
    market: FacebookMarketplace,
    listing: Listing,
    clock: SimpleNamespace,
) -> None:
    market.logger = None
    assert market.get_listing_details(
        listing.post_url, FacebookItemConfig(name="test", search_phrases="pc")
    ) == (listing, False)
