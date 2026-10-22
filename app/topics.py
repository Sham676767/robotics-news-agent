"""Collected legal topics retain source text and extracted document evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceLink:
    url: str
    text: str = ""


@dataclass(frozen=True, slots=True)
class Article:
    source_id: str
    source_name: str
    source_kind: str
    url: str
    title: str
    text: str
    published_at: datetime | None
    links: tuple[SourceLink, ...] = ()


@dataclass(frozen=True, slots=True)
class PrimaryReference:
    kind: str
    citation: str
    url: str
    excerpt: str
    # Availability of a URL is not a legal opinion or a check of current law.
    availability_verified: bool = False


@dataclass(frozen=True, slots=True)
class Topic:
    id: str
    title: str
    articles: tuple[Article, ...]
    references: tuple[PrimaryReference, ...] = ()

    @property
    def published_at(self) -> datetime | None:
        dates = [article.published_at for article in self.articles if article.published_at is not None]
        return max(dates) if dates else None


def topic_to_dict(topic: Topic) -> dict[str, Any]:
    return {
        "id": topic.id, "title": topic.title,
        "published_at": topic.published_at.isoformat() if topic.published_at else None,
        "articles": [
            {"source_id": item.source_id, "source_name": item.source_name,
             "source_kind": item.source_kind, "url": item.url, "title": item.title,
             "text": item.text, "published_at": item.published_at.isoformat() if item.published_at else None,
             "links": [{"url": link.url, "text": link.text} for link in item.links]}
            for item in topic.articles
        ],
        "primary_references": [
            {"kind": ref.kind, "citation": ref.citation, "url": ref.url,
             "excerpt": ref.excerpt, "availability_verified": ref.availability_verified}
            for ref in topic.references
        ],
    }


def topic_from_dict(data: dict[str, Any]) -> Topic:
    return Topic(
        id=data["id"], title=data["title"],
        articles=tuple(Article(
            source_id=item["source_id"], source_name=item["source_name"], source_kind=item["source_kind"],
            url=item["url"], title=item["title"], text=item["text"],
            published_at=datetime.fromisoformat(item["published_at"]) if item["published_at"] else None,
            links=tuple(SourceLink(**link) for link in item.get("links", [])),
        ) for item in data["articles"]),
        references=tuple(PrimaryReference(**ref) for ref in data.get("primary_references", [])),
    )
