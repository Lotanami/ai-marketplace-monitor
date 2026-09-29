"""Public HardwareSwapUK selling posts through the shared marketplace pipeline."""

import re
import time
from dataclasses import dataclass
from typing import Any, Generator, Type

import requests

from .listing import Listing
from .marketplace import ItemConfig, Marketplace, MarketplaceConfig
from .utils import CounterItem, counter, is_substring


@dataclass
class HardwareSwapUKConfig(MarketplaceConfig):
    market_type: str = "hardwareswapuk"

    def handle_market_type(self: "HardwareSwapUKConfig") -> None:
        if self.market_type != "hardwareswapuk":
            raise ValueError("HardwareSwapUK requires market_type='hardwareswapuk'.")


class HardwareSwapUKMarketplace(Marketplace):
    name = "hardwareswapuk"

    @classmethod
    def get_config(cls: Type["HardwareSwapUKMarketplace"], **kwargs: Any) -> HardwareSwapUKConfig:
        return HardwareSwapUKConfig(**kwargs)

    @classmethod
    def get_item_config(cls: Type["HardwareSwapUKMarketplace"], **kwargs: Any) -> ItemConfig:
        return ItemConfig(**kwargs)

    @staticmethod
    def _listing(post: dict[str, Any], item_name: str) -> Listing:
        post_id = post["id"]
        if not isinstance(post_id, str) or not re.fullmatch(r"[a-z0-9]+", post_id):
            raise ValueError("Invalid Reddit post ID")
        title = post["title"]
        body = post.get("selftext", "")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("Invalid Reddit post text")
        text = title + "\n" + body
        price = re.search(
            r"£\s*\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s*GBP\b", text, re.I
        )
        location = re.search(
            r"(?im)^\s*\**(?:location|collection(?: from)?)\s*:\s*\**\s*([^\n]+)", body
        )
        if location is None:
            location = re.search(r"\[(?:location|loc)\s*:\s*([^\]]+)\]", title, re.I)
        return Listing(
            marketplace="hardwareswapuk",
            name=item_name,
            id=post_id,
            title=title,
            image="",
            price=price.group(0) if price else "Not stated",
            post_url=f"https://www.reddit.com/comments/{post_id}/",
            location=location.group(1).strip(" *\r") if location else "Not stated",
            seller=post.get("author") or "Unknown",
            condition="Not stated",
            # Keep the complete body, including CPU/GPU/RAM/storage specifications.
            description=body,
        )

    def search(
        self: "HardwareSwapUKMarketplace", item_config: ItemConfig
    ) -> Generator[Listing, None, None]:
        if self.logger:
            self.logger.info("[HardwareSwapUK] Scanning newest posts")
        started = time.perf_counter()
        try:
            with requests.get(
                "https://www.reddit.com/r/HardwareSwapUK/new.json",
                params={"limit": 100, "raw_json": 1},
                headers={
                    "User-Agent": "AI-Marketplace-Monitor/0.10 (public HardwareSwapUK listings)"
                },
                timeout=30,
            ) as response:
                response.raise_for_status()
                children = response.json()["data"]["children"]
            if not isinstance(children, list):
                raise ValueError("Invalid Reddit listing response")
        except (requests.RequestException, ValueError, KeyError, TypeError):
            if self.logger:
                self.logger.warning("[HardwareSwapUK] Public feed unavailable; skipping this scan")
            return
        finally:
            if self.logger:
                self.logger.info(
                    "[Timing] HardwareSwapUK retrieval: %.1fs", time.perf_counter() - started
                )

        item_config.searched_count += 1
        counter.increment(CounterItem.SEARCH_PERFORMED, item_config.name)
        candidates = []
        seen = set()
        skipped = duplicates = 0
        for child in children[:100]:
            try:
                post = child["data"]
                title = post["title"]
                if (
                    not re.search(r"\[SG\]", title, re.I)
                    or re.search(r"\[(?:BG|SP)\]", title, re.I)
                    or post.get("selftext") in ("[removed]", "[deleted]")
                    or re.search(r"sold|closed", str(post.get("link_flair_text", "")), re.I)
                ):
                    skipped += 1
                    continue
                listing = self._listing(post, item_config.name)
                if listing.id in seen or Listing.from_cache(listing.post_url) is not None:
                    duplicates += 1
                    continue
                seen.add(listing.id)
                text = listing.title + " " + listing.description
                if (
                    (item_config.antikeywords and is_substring(item_config.antikeywords, text))
                    or (item_config.keywords and not is_substring(item_config.keywords, text))
                    or listing.seller
                    in (item_config.exclude_sellers or self.config.exclude_sellers or [])
                ):
                    skipped += 1
                    continue
                candidates.append(listing)
            except (KeyError, TypeError, ValueError, AttributeError):
                skipped += 1
        # Stable sorting retains Reddit's newest-first order within each group.
        candidates.sort(
            key=lambda item: not bool(
                re.search(
                    r"\b(?:(?:gaming|full|complete|desktop)\s+(?:pc|system)|pc\s+(?:build|system)|desktop|full\s+build)\b",
                    item.title,
                    re.I,
                )
            )
        )
        if self.logger:
            self.logger.info(
                "[HardwareSwapUK] Found %d posts; skipped %d; deduplicated %d; %d candidates",
                len(children[:100]),
                skipped,
                duplicates,
                len(candidates),
            )
        for listing in candidates:
            if self.keyboard_monitor is not None and self.keyboard_monitor.is_paused():
                return
            started = time.perf_counter()
            try:
                counter.increment(CounterItem.LISTING_EXAMINED, item_config.name)
                listing.to_cache(listing.post_url)
                yield listing
            finally:
                if self.logger:
                    self.logger.info(
                        "[Timing] Total listing processing: %.1fs", time.perf_counter() - started
                    )
