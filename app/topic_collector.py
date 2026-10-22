"""Collect -> exact merges -> semantic merges/history -> evidence -> selection."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.openrouter_client import OpenRouterError
from app.primary_evidence import find_primary_references
from app.source_config import CollectionConfig
from app.source_http import SourceFetcher, SourceFetchError
from app.source_parsing import enrich_article, parse_html_listing, parse_rss
from app.topic_dedup import local_deduplicate, semantic_deduplicate
from app.topic_history import TopicHistory
from app.topic_selection import is_fresh, select_topics
from app.topics import Article, topic_to_dict
from app.topic_urls import url_key

logger = logging.getLogger(__name__)


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def collect_topics(config: CollectionConfig, settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        raise ValueError("collect requires OPENROUTER_API_KEY for semantic deduplication")
    now = now or datetime.now(timezone.utc)
    articles: list[Article] = []
    errors: list[dict[str, str]] = []
    with SourceFetcher(config) as fetcher:
        for source in config.sources:
            try:
                page = fetcher.fetch(source.url)
                parsed = (parse_rss(page.text, source, config.max_items_per_source) if source.format == "rss"
                          else parse_html_listing(page.text, source, config.max_items_per_source))
                if not parsed:
                    raise ValueError("No entries matched; source markup/feed may have changed")
                for article in parsed:
                    try:
                        detail = fetcher.fetch(article.url)
                        article = enrich_article(article, detail.text, source, detail.url)
                    except SourceFetchError as exc:
                        errors.append({"source": source.id, "url": article.url, "error": str(exc)})
                        # A full RSS entry can still supply a date and primary link.
                    articles.append(article)
                logger.info("Collected %d entries from %s", len(parsed), source.id)
            except (SourceFetchError, ValueError) as exc:
                logger.warning("Source %s failed: %s", source.id, exc)
                errors.append({"source": source.id, "url": source.url, "error": str(exc)})
        if not articles:
            report = {"status": "unavailable", "selected_topics": [], "source_errors": errors,
                      "created_at": now.isoformat(), "requested_count": config.topics_per_video}
            _write_report(config.output_path, report)
            raise ValueError(f"No articles collected; diagnostics written to {config.output_path}")
        topics = [topic for topic in local_deduplicate(articles) if is_fresh(topic, now, config.freshness_days)]
        topics.sort(key=lambda topic: (topic.published_at, topic.id), reverse=True)
        truncated = max(0, len(topics) - config.max_candidates)
        topics = topics[:config.max_candidates]
        with TopicHistory(config.history_path) as history:
            used = history.used_topics()
            used_urls = {url_key(article.url) for topic in used for article in topic.articles}
            exact_excluded = sum(any(url_key(article.url) in used_urls for article in topic.articles) for topic in topics)
            topics = [topic for topic in topics if not any(url_key(article.url) in used_urls for article in topic.articles)]
            try:
                topics, semantic_excluded = semantic_deduplicate(topics, used, settings, config.semantic_batch_size)
            except (OpenRouterError, ValueError):
                _write_report(config.output_path, {
                    "status": "failed", "selected_topics": [], "created_at": now.isoformat(),
                    "source_errors": errors, "error": "Semantic deduplication failed; no selection committed",
                })
                raise
            topics = [replace(topic, references=find_primary_references(topic.articles, config.primary_hosts, fetcher)) for topic in topics]
            ranked = select_topics(topics, config.topics_per_video, config.freshness_days, now)
            selected = [item.topic for item in ranked]
            report = {
                "status": "partial" if errors or len(selected) < config.topics_per_video else "ok",
                "created_at": now.isoformat(), "topics_per_video": config.topics_per_video,
                "freshness_days": config.freshness_days, "audience": ["business", "legal_help"],
                "articles_collected": len(articles), "unique_topics_evaluated": len(topics),
                "candidates_truncated": truncated, "used_topics_excluded": exact_excluded + semantic_excluded,
                "source_errors": errors, "selected_topics": [
                    {**topic_to_dict(item.topic), "score": item.score, "audience": list(item.audience),
                     "selection_reasons": list(item.reasons), "status": "review_required"} for item in ranked
                ],
                "note": "Selection does not mark topics used. Confirm with mark-used after actual use. Legal review is required.",
            }
            history.save_selected(selected)
            _write_report(config.output_path, report)
    return report
