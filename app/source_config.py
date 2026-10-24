"""Read the explicitly configured source list; no hard-coded scraping selectors."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import soupsieve
import yaml


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    name: str
    url: str
    format: str
    kind: str
    item_selector: str = ""
    title_selector: str = ""
    link_selector: str = "a[href]"
    date_selector: str = "time"
    summary_selector: str = ""
    article_selector: str = "article, main"
    link_pattern: str = ""
    article_https: bool = False
    article_trailing_slash: bool = False


@dataclass(frozen=True, slots=True)
class CollectionConfig:
    sources: tuple[SourceConfig, ...]
    primary_hosts: tuple[str, ...]
    freshness_days: int
    topics_per_video: int = 1
    max_items_per_source: int = 15
    max_candidates: int = 60
    semantic_batch_size: int = 12
    fetch_timeout: float = 12.0
    fetch_attempts: int = 2
    max_response_bytes: int = 4_000_000
    history_path: Path = Path("data/topic_history.sqlite3")
    output_path: Path = Path("data/collected_topics.json")


def _positive(data: dict[str, Any], name: str, default: int) -> int:
    value = data.get(name, default)
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _text(data: dict[str, Any], name: str, default: str | None = None) -> str:
    value = data.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def load_source_config(path: Path) -> CollectionConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("Invalid sources YAML") from exc
    if not isinstance(data, dict):
        raise ValueError("sources.yaml must be a mapping")
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("sources must be a non-empty array")
    sources: list[SourceConfig] = []
    ids: set[str] = set()
    for item in raw_sources:
        if not isinstance(item, dict):
            raise ValueError("Each source must be a mapping")
        if item.get("enabled", True) is False:
            continue
        source_id, name, url = (_text(item, key) for key in ("id", "name", "url"))
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"Invalid source URL for {source_id}")
        if source_id in ids:
            raise ValueError("Duplicate source id")
        ids.add(source_id)
        format_, kind = _text(item, "format"), _text(item, "kind")
        if format_ not in {"rss", "html"} or kind not in {"official", "media"}:
            raise ValueError(f"Unsupported source format/kind: {source_id}")
        selectors = {key: item.get(key, default) for key, default in (
            ("item_selector", ""), ("title_selector", ""), ("link_selector", "a[href]"),
            ("date_selector", "time"), ("summary_selector", ""), ("article_selector", "article, main"),
        )}
        for selector in selectors.values():
            if not isinstance(selector, str):
                raise ValueError("CSS selectors must be strings")
            if selector:
                try:
                    soupsieve.compile(selector)
                except soupsieve.SelectorSyntaxError as exc:
                    raise ValueError(f"Invalid CSS selector for {source_id}") from exc
        if format_ == "html" and not selectors["item_selector"]:
            raise ValueError(f"HTML source {source_id} requires item_selector")
        pattern = item.get("link_pattern", "")
        if not isinstance(pattern, str):
            raise ValueError("link_pattern must be a string")
        if pattern:
            import re
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid link_pattern for {source_id}") from exc
        url_rules = {key: item.get(key, False) for key in ("article_https", "article_trailing_slash")}
        if any(type(value) is not bool for value in url_rules.values()):
            raise ValueError("Article URL rules must be booleans")
        sources.append(SourceConfig(source_id, name, url, format_, kind, **selectors, link_pattern=pattern, **url_rules))
    if not sources:
        raise ValueError("At least one enabled source is required")
    hosts = data.get("primary_hosts")
    if not isinstance(hosts, list) or not hosts or any(
        not isinstance(host, str) or not host or "/" in host or ":" in host or " " in host for host in hosts
    ):
        raise ValueError("primary_hosts must be an explicit list of host names")
    selection = data.get("collection", {})
    if not isinstance(selection, dict):
        raise ValueError("collection must be a mapping")
    if "freshness_days" not in selection:
        raise ValueError("collection.freshness_days must be configured")
    batch_size = _positive(selection, "semantic_batch_size", 12)
    if not 2 <= batch_size <= 30:
        raise ValueError("semantic_batch_size must be between 2 and 30")
    timeout = selection.get("fetch_timeout", 12)
    import math
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("fetch_timeout must be positive and finite")
    return CollectionConfig(
        sources=tuple(sources), primary_hosts=tuple(host.lower() for host in hosts),
        freshness_days=_positive(selection, "freshness_days", 30),
        topics_per_video=_positive(selection, "topics_per_video", 1),
        max_items_per_source=_positive(selection, "max_items_per_source", 15),
        max_candidates=_positive(selection, "max_candidates", 60),
        semantic_batch_size=batch_size, fetch_timeout=float(timeout),
        fetch_attempts=_positive(selection, "fetch_attempts", 2),
        max_response_bytes=_positive(selection, "max_response_bytes", 4_000_000),
        history_path=Path(_text(selection, "history_path", "data/topic_history.sqlite3")),
        output_path=Path(_text(selection, "output_path", "data/collected_topics.json")),
    )
