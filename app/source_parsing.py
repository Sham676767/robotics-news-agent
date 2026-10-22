"""RSS/Atom and configurable HTML parsing; dates come only from source metadata."""
from __future__ import annotations

import calendar
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
from bs4 import BeautifulSoup, Tag

from app.source_config import SourceConfig
from app.topics import Article, SourceLink
from app.topic_urls import canonical_url

MSK = timezone(timedelta(hours=3))
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def clean_text(value: str) -> str:
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())


def _article_url(value: str, source: SourceConfig) -> str:
    parsed = urlsplit(canonical_url(urljoin(source.url, value)))
    if parsed.hostname == urlsplit(source.url).hostname:
        scheme = "https" if source.article_https else parsed.scheme
        path = parsed.path.rstrip("/") + "/" if source.article_trailing_slash else parsed.path
        return urlunsplit((scheme, parsed.netloc, path, parsed.query, ""))
    return urlunsplit(parsed)


def parse_date(value: str) -> datetime | None:
    text = " ".join(value.split()).strip()
    if not text:
        return None
    for month, name in enumerate(MONTHS, 1):
        text = re.sub(rf"\b{name}\b", f"{month:02}", text, flags=re.I)
    text = re.sub(r"\s+(?:года|г\.)\b", "", text)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return result.replace(tzinfo=MSK).astimezone(timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except ValueError:
        pass
    for format_ in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d %m %Y %H:%M", "%d %m %Y"):
        try:
            return datetime.strptime(text, format_).replace(tzinfo=MSK).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        result = parsedate_to_datetime(text)
        return result.replace(tzinfo=MSK).astimezone(timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def extract_links(node: BeautifulSoup | Tag, base_url: str) -> tuple[SourceLink, ...]:
    links: dict[str, SourceLink] = {}
    for anchor in node.select("a[href]"):
        try:
            url = canonical_url(urljoin(base_url, str(anchor.get("href", ""))))
        except ValueError:
            continue
        links[url] = SourceLink(url, anchor.get_text(" ", strip=True))
    return tuple(links.values())


def parse_rss(content: str, source: SourceConfig, limit: int) -> list[Article]:
    feed = feedparser.parse(content)
    if not feed.get("version") and not feed.entries:
        raise ValueError("Response is not an RSS/Atom feed")
    articles: list[Article] = []
    for entry in feed.entries[:limit]:
        title = clean_text(str(entry.get("title", "")))
        try:
            url = _article_url(str(entry.get("link", "")), source)
        except ValueError:
            continue
        if not title or not entry.get("link"):
            continue
        raw = " ".join(str(item.get("value", "")) for item in entry.get("content", [])) or str(entry.get("summary", ""))
        published = parse_date(str(entry.get("published") or entry.get("updated") or ""))
        if published is None:
            struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if struct:
                published = datetime.fromtimestamp(calendar.timegm(struct), timezone.utc)
        articles.append(Article(source.id, source.name, source.kind, url, title, clean_text(raw), published,
                                extract_links(BeautifulSoup(raw, "html.parser"), url)))
    return articles


def parse_html_listing(content: str, source: SourceConfig, limit: int) -> list[Article]:
    soup = BeautifulSoup(content, "html.parser")
    result: list[Article] = []
    seen: set[str] = set()
    for node in soup.select(source.item_selector):
        title_node = node.select_one(source.title_selector) if source.title_selector else node
        anchor = node if node.name == "a" else node.select_one(source.link_selector)
        if title_node is None or anchor is None or not anchor.get("href"):
            continue
        try:
            url = _article_url(str(anchor["href"]), source)
        except ValueError:
            continue
        if source.link_pattern and not re.search(source.link_pattern, url):
            continue
        title = title_node.get_text(" ", strip=True)
        if not title or url in seen:
            continue
        seen.add(url)
        date_node = node.select_one(source.date_selector) if source.date_selector else None
        date_value = str(date_node.get("datetime") or date_node.get("content") or date_node.get_text(" ", strip=True)) if date_node else ""
        # Listing containers sometimes expose a plain date instead of a time tag.
        if not date_value:
            match = re.search(r"\b\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?\b", node.get_text(" ", strip=True))
            date_value = match.group() if match else ""
        summary = node.select_one(source.summary_selector) if source.summary_selector else None
        result.append(Article(source.id, source.name, source.kind, url, title,
                              summary.get_text(" ", strip=True) if summary else "", parse_date(date_value)))
        if len(result) >= limit:
            break
    return result


def enrich_article(article: Article, content: str, source: SourceConfig, final_url: str) -> Article:
    soup = BeautifulSoup(content, "html.parser")
    # Metadata is read before removing navigation and scripts.
    published = article.published_at
    if published is None:
        date_node = soup.select_one('meta[property="article:published_time"], meta[itemprop="datePublished"], time[datetime], [itemprop="datePublished"]')
        if date_node:
            published = parse_date(str(date_node.get("content") or date_node.get("datetime") or date_node.get_text(" ", strip=True)))
    root = soup.select_one(source.article_selector) if source.article_selector else None
    root = root if root is not None else soup.body or soup
    for tag in root.select("script, style, nav, footer, header, aside, form"):
        tag.decompose()
    # Some sites put the date only in the article text.
    if published is None:
        text = root.get_text(" ", strip=True)
        match = re.search(r"\b(?:\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?|\d{1,2}\s+(?:" + "|".join(MONTHS) + r")\s+\d{4})\b", text, re.I)
        published = parse_date(match.group()) if match else None
    text = " ".join(root.get_text(" ", strip=True).split())
    return replace(article, url=canonical_url(final_url), text=text or article.text,
                   published_at=published, links=tuple(dict.fromkeys((*article.links, *extract_links(root, final_url)))))
