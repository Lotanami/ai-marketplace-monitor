"""Discord payload, delivery, configuration, and secret handling regressions."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from ai_marketplace_monitor.ai import AIResponse
from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.discord import DiscordNotificationConfig
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.notification import NotificationConfig, NotificationStatus
from ai_marketplace_monitor.user import UserConfig
from ai_marketplace_monitor.webui.secrets_redact import redact, restore

WEBHOOK = "https://discord.com/api/webhooks/123456/test-secret"
NEW = NotificationStatus.NOT_NOTIFIED


@pytest.fixture
def listing() -> Listing:
    return Listing(
        marketplace="facebook",
        name="chair",
        id="123",
        title="Oak chair",
        image="",
        price="£25",
        post_url="https://www.facebook.com/marketplace/item/123?ref=search",
        location="London",
        seller="",
        condition="Used",
        description="Solid oak, good condition.",
    )


@pytest.fixture
def config() -> DiscordNotificationConfig:
    return DiscordNotificationConfig(
        name="discord", discord_webhook_url=WEBHOOK, max_retries=2, retry_delay=0
    )


def response(status: int = 200, retry_after: float | None = None) -> Mock:
    return Mock(
        status_code=status, headers={}, json=Mock(return_value={"retry_after": retry_after})
    )


def test_embed_contains_listing_and_ai(
    config: DiscordNotificationConfig, listing: Listing
) -> None:
    with patch("ai_marketplace_monitor.discord.requests.post", return_value=response()) as post:
        assert config.notify([listing], [AIResponse(5, "Great value")], [NEW])
    payload = post.call_args.kwargs["json"]
    embed = payload["embeds"][0]
    assert embed["title"] == listing.title
    assert embed["description"] == listing.description
    assert embed["url"] == listing.post_url.split("?")[0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert fields == {
        "Price": "£25",
        "Location": "London",
        "AI rating": "Great deal (5/5)",
        "AI summary": "Great value",
    }
    assert payload["allowed_mentions"] == {"parse": []}
    assert post.call_args.kwargs["params"] == {"wait": "true"}
    assert post.call_args.kwargs["timeout"] == 30
    assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("ratings", [[], [AIResponse(5, AIResponse.NOT_EVALUATED)]])
def test_unevaluated_listing_omits_ai(
    config: DiscordNotificationConfig, listing: Listing, ratings: list[AIResponse]
) -> None:
    with patch("ai_marketplace_monitor.discord.requests.post", return_value=response()) as post:
        assert config.notify([listing], ratings, [NEW])
    assert [field["name"] for field in post.call_args.kwargs["json"]["embeds"][0]["fields"]] == [
        "Price",
        "Location",
    ]


def test_long_embed_fits_discord_limits(
    config: DiscordNotificationConfig, listing: Listing
) -> None:
    listing.title = listing.description = listing.price = listing.location = "x" * 10000
    with patch("ai_marketplace_monitor.discord.requests.post", return_value=response()) as post:
        assert config.notify([listing], [AIResponse(4, "y" * 10000)], [NEW])
    embed = post.call_args.kwargs["json"]["embeds"][0]
    assert len(embed["title"]) <= 256
    assert len(embed["description"]) <= 4096
    assert all(len(field["value"]) <= 1024 for field in embed["fields"])
    assert (
        len(embed["title"])
        + len(embed["description"])
        + sum(len(field["name"]) + len(field["value"]) for field in embed["fields"])
        <= 6000
    )


def test_status_filtering_and_force(config: DiscordNotificationConfig, listing: Listing) -> None:
    with patch("ai_marketplace_monitor.discord.requests.post", return_value=response()) as post:
        assert not config.notify([listing], [], [NotificationStatus.NOTIFIED])
        post.assert_not_called()
        assert config.notify([listing], [], [NotificationStatus.NOTIFIED], force=True)


@pytest.mark.parametrize(
    "status",
    [
        NotificationStatus.EXPIRED,
        NotificationStatus.LISTING_CHANGED,
        NotificationStatus.LISTING_DISCOUNTED,
    ],
)
def test_existing_update_statuses_are_sent(
    config: DiscordNotificationConfig, listing: Listing, status: NotificationStatus
) -> None:
    with patch("ai_marketplace_monitor.discord.requests.post", return_value=response()):
        assert config.notify([listing], [], [status])


def test_missing_or_disabled_config_does_not_send(listing: Listing) -> None:
    with patch("ai_marketplace_monitor.discord.requests.post") as post:
        assert not DiscordNotificationConfig(name="empty").notify([listing], [], [NEW])
        assert not DiscordNotificationConfig(
            name="off", discord_webhook_url=WEBHOOK, enabled=False
        ).notify([listing], [], [NEW])
        assert not NotificationConfig.notify_all(
            UserConfig(name="unconfigured"),
            [listing],
            [AIResponse(5, AIResponse.NOT_EVALUATED)],
            [NEW],
        )
        post.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://discord.com/api/webhooks/1/token",
        "https://example.com/api/webhooks/1/token",
        123,
    ],
)
def test_invalid_webhook_rejected_without_disclosing_value(value: str | int) -> None:
    with pytest.raises(ValueError, match="Discord HTTPS webhook URL"):
        DiscordNotificationConfig(name="bad", discord_webhook_url=value)


@pytest.mark.parametrize("use_header", [False, True])
def test_rate_limit_wait_and_retry(
    config: DiscordNotificationConfig, listing: Listing, use_header: bool
) -> None:
    limited = response(429, 2.5)
    if use_header:
        limited.headers = {"Retry-After": "2.5"}
    with (
        patch("ai_marketplace_monitor.discord.requests.post", side_effect=[limited, response()]),
        patch("ai_marketplace_monitor.discord.time.monotonic", return_value=100),
        patch("ai_marketplace_monitor.discord.time.sleep") as sleep,
    ):
        assert config.notify([listing], [], [NEW])
    assert any(call.args == (2.5,) for call in sleep.call_args_list)


def test_http_failure_retried_and_batch_failure_not_success(
    config: DiscordNotificationConfig, listing: Listing
) -> None:
    with patch(
        "ai_marketplace_monitor.discord.requests.post",
        side_effect=[response(), response(500), response(500)],
    ) as post:
        assert not config.notify([listing, listing], [], [NEW, NEW])
    assert post.call_count == 3


def test_request_error_does_not_log_webhook_secret(
    config: DiscordNotificationConfig, listing: Listing
) -> None:
    logger = Mock()
    with patch(
        "ai_marketplace_monitor.discord.requests.post", side_effect=requests.Timeout(WEBHOOK)
    ):
        assert not config.notify([listing], [], [NEW], logger=logger)
    assert WEBHOOK not in str(logger.mock_calls)
    assert "test-secret" not in repr(config)


def test_notify_with_configuration_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, listing: Listing
) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    path = tmp_path / "discord.toml"
    path.write_text("""[marketplace]
[item]
[notification.discord]
discord_webhook_url = "${DISCORD_WEBHOOK_URL}"
[user.me]
notify_with = ["discord"]
[user.other]
notify_with = []
""")
    parsed = Config([path])
    assert parsed.user["me"].discord_webhook_url == WEBHOOK
    assert parsed.user["other"].discord_webhook_url is None
    with patch("ai_marketplace_monitor.discord.requests.post", return_value=response()) as post:
        assert NotificationConfig.notify_all(
            parsed.user["me"], [listing], [AIResponse(5, AIResponse.NOT_EVALUATED)], [NEW]
        )
    assert post.call_count == 1
    assert UserConfig(name="direct", discord_webhook_url=WEBHOOK).discord_webhook_url == WEBHOOK


def test_webhook_secret_redaction_round_trip() -> None:
    original = f'[notification.discord]\ndiscord_webhook_url = "{WEBHOOK}"\n'
    masked, secrets = redact(original)
    assert WEBHOOK not in masked
    assert restore(masked, secrets) == original
