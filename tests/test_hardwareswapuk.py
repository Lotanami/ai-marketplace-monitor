"""HardwareSwapUK discovery uses mocked public responses only."""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from ai_marketplace_monitor import hardwareswapuk, monitor
from ai_marketplace_monitor.ai import AIResponse, OpenAIBackend, OpenAIConfig
from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.hardwareswapuk import HardwareSwapUKConfig, HardwareSwapUKMarketplace
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.marketplace import ItemConfig
from ai_marketplace_monitor.monitor import MarketplaceMonitor


@pytest.fixture
def item() -> ItemConfig:
    return ItemConfig(
        name="pc",
        marketplace="hardwareswapuk",
        search_phrases="gaming pc",
        rating=4,
        notify=["me"],
    )


@pytest.fixture
def market(monkeypatch: pytest.MonkeyPatch) -> HardwareSwapUKMarketplace:
    result = HardwareSwapUKMarketplace(
        "hardwareswapuk", None, logger=logging.getLogger("reddit-test")
    )
    result.configure(HardwareSwapUKConfig(name="hardwareswapuk"))
    stored = {}
    monkeypatch.setattr(Listing, "from_cache", lambda key: stored.get(key))
    monkeypatch.setattr(Listing, "to_cache", lambda listing, key: stored.update({key: listing}))
    monkeypatch.setattr(monitor.time, "sleep", Mock())
    return result


def response(monkeypatch: pytest.MonkeyPatch, posts: list[dict]) -> Mock:
    request = Mock()
    request.return_value.__enter__ = Mock(return_value=request.return_value)
    request.return_value.__exit__ = Mock(return_value=False)
    request.return_value.json.return_value = {
        "data": {"children": [{"data": post} for post in posts]}
    }
    monkeypatch.setattr(hardwareswapuk.requests, "get", request)
    return request


def post(number: str, title: str = "[SG] Gaming PC [W] £600") -> dict:
    return {
        "id": number,
        "title": title,
        "selftext": "**Location:** Leeds\nRyzen 5600 / RTX 3070 / 32GB RAM / 1TB SSD",
        "author": "seller",
    }


def test_extract_order_filter_and_repeat_dedup(
    market: HardwareSwapUKMarketplace, item: ItemConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = response(
        monkeypatch,
        [
            post("a", "[SG] GPU £200"),
            post("b"),
            post("c", "[BG] PC"),
            post("d", "[SP] PC"),
            post("e", "[SG] [BG] PC"),
            post("b"),
            {"title": "[SG] missing id"},
        ],
    )
    listings = list(market.search(item))
    assert [x.id for x in listings] == ["b", "a"]
    assert listings[0].price == "£600"
    assert listings[0].location == "Leeds"
    assert "RTX 3070" in listings[0].description
    assert listings[0].post_url == "https://www.reddit.com/comments/b/"
    assert list(market.search(item)) == []
    assert request.call_args.kwargs["timeout"] == 30
    assert request.call_args.kwargs["params"] == {"limit": 100, "raw_json": 1}


def test_unknown_fields_and_body_price() -> None:
    listing = HardwareSwapUKMarketplace._listing(
        {"id": "abc", "title": "[SG] PC", "selftext": "Price: 450 GBP\nCPU: i5"}, "pc"
    )
    assert listing.price == "450 GBP"
    assert listing.location == "Not stated"


@pytest.mark.parametrize(
    "failure", [requests.HTTPError("403"), requests.Timeout(), ValueError("not json")]
)
def test_public_access_failure_is_nonfatal(
    market: HardwareSwapUKMarketplace,
    item: ItemConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
) -> None:
    request = response(monkeypatch, [])
    request.side_effect = failure
    assert list(market.search(item)) == []
    assert "Public feed unavailable" in caplog.text


def test_existing_ai_threshold_and_notification_pipeline(
    market: HardwareSwapUKMarketplace,
    item: ItemConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    response(monkeypatch, [post("a"), post("b")])
    instance = MarketplaceMonitor.__new__(MarketplaceMonitor)
    instance.config = SimpleNamespace(user={"me": Mock()})
    instance.logger = logging.getLogger("reddit-test")
    instance.evaluate_by_ai = Mock(
        side_effect=[AIResponse(3, "Too expensive"), AIResponse(5, "Good deal")]
    )
    user = Mock()
    user.notification_status.return_value = None
    monkeypatch.setattr(monitor, "User", Mock(return_value=user))
    instance.search_item(market.config, market, item)
    assert instance.evaluate_by_ai.call_count == 2
    assert [x.id for x in user.notify.call_args.args[0]] == ["b"]
    assert "Sent 2 posts to AI evaluation" in caplog.text
    instance.search_item(market.config, market, item)
    assert instance.evaluate_by_ai.call_count == 2
    assert "Sent 0 posts to AI evaluation" in caplog.text


def test_registration_without_city(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[marketplace.hardwareswapuk]\nenabled=true\n[user.me]\n[item.pc]\nmarketplace="hardwareswapuk"\nsearch_phrases="gaming pc"\n'
    )
    parsed = Config([config])
    assert isinstance(parsed.marketplace["hardwareswapuk"], HardwareSwapUKConfig)
    assert parsed.item["pc"].marketplace == "hardwareswapuk"
    instance = MarketplaceMonitor.__new__(MarketplaceMonitor)
    instance.config = parsed
    # The public source itself must never introduce a credentials requirement.
    parsed.marketplace = {"hardwareswapuk": parsed.marketplace["hardwareswapuk"]}
    assert instance._has_marketplace_credentials()


def test_reddit_prompt_source(item: ItemConfig) -> None:
    backend = OpenAIBackend(OpenAIConfig(name="test", api_key="test"))
    listing = HardwareSwapUKMarketplace._listing(post("a"), "pc")
    assert "from r/HardwareSwapUK." in backend.get_prompt(
        listing, item, HardwareSwapUKConfig(name="hardwareswapuk")
    )
