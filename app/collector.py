from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml
from dateutil import parser as date_parser

from .models import NewsItem

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 8.0
MAX_WORKERS = 8


def load_sources(path: str | Path = "config/sources.yaml") -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data.get("sources", [])


def clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    text = html.unescape(text)
    return text.strip()


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


def _feed_image_url(entry, page_url: str) -> str | None:
    """Extract the best image URL exposed directly by an RSS/Atom entry."""
    candidates: list[str] = []

    media_content = entry.get("media_content") or []
    media_thumbnail = entry.get("media_thumbnail") or []
    enclosures = entry.get("enclosures") or []

    for item in [*media_content, *media_thumbnail, *enclosures]:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("href")
        media_type = str(item.get("type") or item.get("medium") or "").lower()
        if url and (not media_type or "image" in media_type):
            candidates.append(str(url))

    # feedparser may expose namespaced fields as a flat key on some feeds.
    for key in ("media_url", "image_url", "thumbnail", "image"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
        elif isinstance(value, dict):
            url = value.get("url") or value.get("href")
            if url:
                candidates.append(str(url))

    for value in candidates:
        value = value.strip()
        if value.startswith("//"):
            value = "https:" + value
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith(("/", "./")):
            return httpx.URL(page_url).join(value).human_repr()
    return None


def collect_from_source(source: dict, limit: int = 30) -> list[NewsItem]:
    url = source["url"]
    name = source["name"]
    logger.info("Fetching %s", name)

    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Robotics News Agent/1.0"},
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to fetch %s: %s", name, exc)
        return []

    if getattr(feed, "bozo", False):
        logger.warning("Feed parser warning for %s: %s", name, feed.bozo_exception)

    items: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        title = clean_text(entry.get("title") or "")
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        summary = clean_text(entry.get("summary") or entry.get("description") or "")
        image_url = _feed_image_url(entry, link)
        items.append(
            NewsItem(
                source=name,
                title=title,
                url=link,
                published_at=parse_date(entry),
                summary=summary,
                language=source.get("language", ""),
                topics=tuple(source.get("topics", [])),
                image_url=image_url,
            )
        )
    return items


def collect_all(path: str | Path = "config/sources.yaml") -> list[NewsItem]:
    sources = load_sources(path)
    all_items: list[NewsItem] = []

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(sources)))) as executor:
        futures = {
            executor.submit(collect_from_source, source): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                all_items.extend(future.result())
            except Exception:
                logger.exception("Failed to collect source: %s", source.get("name"))

    return all_items


def collect_news(path: str = "config/sources.yaml") -> list[NewsItem]:
    """Public interface for news collection pipeline."""
    return collect_all(path)
