"""Bounded home-feed discovery reuses the existing listing pipeline."""

import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_marketplace_monitor import facebook, monitor
from ai_marketplace_monitor.ai import AIResponse
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
)
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.monitor import MarketplaceMonitor


def url(number: int) -> str:
    return f"https://www.facebook.com/marketplace/item/{number}/"


@pytest.fixture
def market(monkeypatch: pytest.MonkeyPatch, listing: Listing) -> FacebookMarketplace:
    result = FacebookMarketplace("facebook", None, logger=logging.getLogger("for-you-test"))
    result.configure(
        FacebookMarketplaceConfig(name="facebook", search_city="london", scan_for_you=True)
    )
    result.page = Mock()
    result.persistent_context = Mock()
    result.goto_url = Mock()
    result.check_listing = Mock(return_value=True)
    result.get_listing_details = Mock(
        side_effect=lambda post_url, *args, **kwargs: (
            replace(
                listing, id=post_url.rstrip("/").split("/")[-1], post_url=post_url, title=post_url
            ),
            False,
        )
    )
    monkeypatch.setattr(Listing, "from_cache", Mock(return_value=None))
    monkeypatch.setattr(facebook.time, "sleep", Mock())
    return result


@pytest.mark.parametrize(
    "settings",
    [
        {"scan_for_you": "true"},
        {"for_you_max_listings": 0},
        {"for_you_max_listings": 101},
        {"for_you_max_listings": True},
        {"for_you_scrolls": -1},
        {"for_you_scrolls": 21},
        {"for_you_scrolls": 1.5},
    ],
)
def test_invalid_feed_settings(settings: dict) -> None:
    with pytest.raises(ValueError):
        FacebookMarketplaceConfig(name="facebook", **settings)


def test_feed_defaults_off() -> None:
    config = FacebookMarketplaceConfig(name="facebook")
    assert (config.scan_for_you, config.for_you_max_listings, config.for_you_scrolls) == (
        False,
        25,
        2,
    )


def test_bounded_link_collection(market: FacebookMarketplace) -> None:
    market.config.for_you_max_listings = 3
    links = market.page.locator.return_value
    links.evaluate_all.side_effect = [
        [url(1), url(1) + "?tracking=1", "https://example.com/marketplace/item/9/"],
        [url(2), url(3), url(4)],
    ]
    assert market._for_you_urls() == [url(1), url(2), url(3)]
    market.page.goto.assert_called_once_with(
        "https://www.facebook.com/marketplace/", timeout=30000
    )
    assert market.page.evaluate.call_count == 1


def test_scroll_budget_even_when_feed_repeats(market: FacebookMarketplace) -> None:
    market.page.locator.return_value.evaluate_all.return_value = [url(1)]
    assert market._for_you_urls() == [url(1)]
    assert market.page.evaluate.call_count == 2
    assert market.page.locator.return_value.evaluate_all.call_count == 3


def test_only_six_new_candidates_reach_existing_ai_and_notifier(
    market: FacebookMarketplace,
    listing: Listing,
    item_config: FacebookItemConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(market, "_for_you_urls", Mock(return_value=[url(i) for i in range(1, 26)]))
    monkeypatch.setattr(
        Listing,
        "from_cache",
        lambda post_url: listing if int(post_url.rstrip("/").split("/")[-1]) <= 19 else None,
    )
    search_page = Mock()
    search_page.get_listings.return_value = []
    monkeypatch.setattr(facebook, "FacebookSearchResultPage", Mock(return_value=search_page))
    instance = MarketplaceMonitor.__new__(MarketplaceMonitor)
    instance.logger = None
    instance.config = SimpleNamespace(user={"user1": Mock()})
    instance.evaluate_by_ai = Mock(return_value=AIResponse(5, "Great deal"))
    user = Mock()
    user.notification_status.return_value = None
    monkeypatch.setattr(monitor, "User", Mock(return_value=user))
    instance.search_item(market.config, market, item_config)
    assert market.get_listing_details.call_count == 6
    assert instance.evaluate_by_ai.call_count == 6
    assert [call.args[0].id for call in instance.evaluate_by_ai.call_args_list] == [
        str(i) for i in range(20, 26)
    ]
    user.notify.assert_called_once()
    assert len(user.notify.call_args.args[0]) == 6
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("[For You]")] == [
        "[For You] Found 25 cards",
        "[For You] 19 already known",
        "[For You] 6 new candidates",
    ]


@pytest.mark.parametrize("enabled", [False, True])
def test_keyword_search_survives_feed_failure(
    market: FacebookMarketplace,
    listing: Listing,
    item_config: FacebookItemConfig,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    market.config.scan_for_you = enabled
    search_page = Mock()
    search_page.get_listings.return_value = [listing]
    monkeypatch.setattr(facebook, "FacebookSearchResultPage", Mock(return_value=search_page))
    feed = Mock(side_effect=ValueError("layout changed"))
    monkeypatch.setattr(market, "_for_you_urls", feed)
    assert [item.id for item in market.search(item_config)] == [listing.id]
    assert feed.call_count == int(enabled)
    assert market.goto_url.call_count == len(item_config.search_phrases)


def test_keyword_ids_and_both_cache_url_forms_skip_details(
    market: FacebookMarketplace,
    listing: Listing,
    item_config: FacebookItemConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(market, "_for_you_urls", Mock(return_value=[url(1), url(2), url(3)]))
    monkeypatch.setattr(
        Listing,
        "from_cache",
        lambda value: listing if value in (url(2), url(3).rstrip("/")) else None,
    )
    assert list(market._search_for_you(item_config, {url(1) + "?tracking=1"})) == []
    market.get_listing_details.assert_not_called()


def test_missing_persistent_session_skips_feed(
    market: FacebookMarketplace, item_config: FacebookItemConfig
) -> None:
    market.persistent_context = None
    assert list(market._search_for_you(item_config, set())) == []
    market.page.goto.assert_not_called()


def test_detail_failure_continues_and_interrupt_propagates(
    market: FacebookMarketplace,
    listing: Listing,
    item_config: FacebookItemConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(market, "_for_you_urls", Mock(return_value=[url(1), url(2)]))
    market.get_listing_details.side_effect = [ValueError("missing"), (listing, False)]
    assert list(market._search_for_you(item_config, set())) == [listing]
    market.get_listing_details.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        list(market._search_for_you(item_config, set()))


def test_repeat_scan_uses_existing_listing_cache(
    market: FacebookMarketplace,
    listing: Listing,
    item_config: FacebookItemConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = {}
    monkeypatch.setattr(market, "_for_you_urls", Mock(return_value=[url(1)]))
    monkeypatch.setattr(Listing, "from_cache", lambda value: stored.get(value))
    monkeypatch.setattr(Listing, "to_cache", lambda value, key: stored.update({key: value}))
    monkeypatch.setattr(facebook, "parse_listing", Mock(return_value=listing))
    monkeypatch.setattr(
        market, "get_listing_details", FacebookMarketplace.get_listing_details.__get__(market)
    )
    assert list(market._search_for_you(item_config, set())) == [listing]
    assert list(market._search_for_you(item_config, set())) == []
    market.goto_url.assert_called_once_with(url(1))


def test_unparseable_feed_logs_and_returns(
    market: FacebookMarketplace,
    item_config: FacebookItemConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    market.page.locator.return_value.evaluate_all.return_value = ["https://example.com/"]
    assert list(market._search_for_you(item_config, set())) == []
    assert "Could not read the home feed" in caplog.text
    market.get_listing_details.assert_not_called()
