from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yaml
from dateutil import parser as date_parser

from .models import NewsItem

logger = logging.getLogger(__name__)


def load_sources(path: str | Path = "config/sources.yaml") -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data.get("sources", [])


def parse_date(entry) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            return date_parser.parse(raw).astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError):
            pass

    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        try:
            return datetime(*struct[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


def collect_from_source(source: dict, limit: int = 30) -> list[NewsItem]:
    url = source["url"]
    name = source["name"]
    logger.info("Fetching %s", name)

    feed = feedparser.parse(url)
    if getattr(feed, "bozo", False):
        logger.warning("Feed parser warning for %s: %s", name, feed.bozo_exception)

    items: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        summary = (entry.get("summary") or entry.get("description") or "").strip()
        items.append(
            NewsItem(
                source=name,
                title=title,
                url=link,
                published_at=parse_date(entry),
                summary=summary,
                language=source.get("language", ""),
                topics=tuple(source.get("topics", [])),
            )
        )
    return items


def collect_all(path: str | Path = "config/sources.yaml") -> list[NewsItem]:
    all_items: list[NewsItem] = []
    for source in load_sources(path):
        try:
            all_items.extend(collect_from_source(source))
        except Exception:
            logger.exception("Failed to collect source: %s", source.get("name"))
    return all_items
def collect_news(path: str = "config/sources.yaml") -> list[NewsItem]:
    """
    Public interface for news collection pipeline.
    """
    return collect_all(path)
