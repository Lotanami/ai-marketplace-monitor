"""Discord incoming-webhook notifications, independent of other push backends."""

import json
import math
import re
import time
from dataclasses import dataclass, field
from logging import Logger
from typing import Any, ClassVar, List

import requests

from .ai import AIResponse
from .listing import Listing
from .notification import NotificationConfig, NotificationStatus


@dataclass
class DiscordNotificationConfig(NotificationConfig):
    notify_method = "discord"
    required_fields: ClassVar[List[str]] = ["discord_webhook_url"]

    discord_webhook_url: str | None = field(default=None, repr=False)

    def handle_discord_webhook_url(self: "DiscordNotificationConfig") -> None:
        if self.discord_webhook_url is None:
            return
        if not isinstance(self.discord_webhook_url, str) or not re.fullmatch(
            r"https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\d+/[\w-]+",
            self.discord_webhook_url.strip(),
        ):
            raise ValueError("discord_webhook_url must be a Discord HTTPS webhook URL.")
        self.discord_webhook_url = self.discord_webhook_url.strip()

    def notify(
        self: "DiscordNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if self.enabled is False or not self._has_required_fields():
            return False
        sent = False
        for index, (listing, status) in enumerate(zip(listings, notification_status)):
            if status == NotificationStatus.NOTIFIED and not force:
                continue
            rating = ratings[index] if index < len(ratings) else None
            # One listing per request; fixed budgets stay below 6000 embed characters.
            embed: dict[str, Any] = {
                "title": (listing.title or "Marketplace listing")[:256],
                "url": listing.post_url.split("?")[0],
                "description": (listing.description or "")[:3000],
                "fields": [
                    {
                        "name": "Price",
                        "value": (listing.price or "Unspecified")[:256],
                        "inline": True,
                    },
                    {
                        "name": "Location",
                        "value": (listing.location or "Unspecified")[:256],
                        "inline": True,
                    },
                ],
            }
            if rating is not None and rating.comment != AIResponse.NOT_EVALUATED:
                embed["fields"].extend(
                    [
                        {
                            "name": "AI rating",
                            "value": f"{rating.conclusion} ({rating.score}/5)"[:256],
                        },
                        {"name": "AI summary", "value": (rating.comment or "No summary")[:1024]},
                    ]
                )
            payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}
            if not self.send_message_with_retry(embed["title"], json.dumps(payload), logger):
                return False
            sent = True
        return sent

    def send_message(
        self: "DiscordNotificationConfig", title: str, message: str, logger: Logger | None = None
    ) -> bool:
        if not self._has_required_fields():
            return False
        # The common retry loop waits retry_delay; additionally honor Discord's deadline.
        wait = getattr(self, "_discord_retry_at", 0.0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            response = requests.post(
                self.discord_webhook_url,
                params={"wait": "true"},
                json=json.loads(message),
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException:
            # Request exceptions include the URL, whose path contains the webhook secret.
            raise RuntimeError("Discord webhook request failed.") from None
        if response.status_code == 429:
            try:
                retry_after = float(
                    response.headers.get("Retry-After") or response.json()["retry_after"]
                )
                if math.isfinite(retry_after) and retry_after >= 0:
                    self._discord_retry_at = time.monotonic() + retry_after
            except (ValueError, TypeError, KeyError):
                pass
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Discord webhook returned HTTP {response.status_code}.")
        return True
