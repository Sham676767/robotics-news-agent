from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import NewsItem

DEFAULT_DB_PATH = "data/news.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    summary TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    topics TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(source, url)
);

CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source);
CREATE INDEX IF NOT EXISTS idx_news_hash ON news_items(content_hash);
"""


def content_hash(item: NewsItem) -> str:
    """Stable hash used to detect the same story across different feeds."""
    normalized = " ".join(item.title.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def save_item(connection: sqlite3.Connection, item: NewsItem) -> bool:
    """Save an item. Returns True when a new record was inserted."""
    published_at = item.published_at.isoformat() if isinstance(item.published_at, datetime) else None
    topics = ",".join(item.topics)
    try:
        connection.execute(
            """
            INSERT INTO news_items
                (source, title, url, published_at, summary, language, topics, content_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                item.source,
                item.title,
                item.url,
                published_at,
                item.summary,
                item.language,
                topics,
                content_hash(item),
            ),
        )
        connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def save_items(connection: sqlite3.Connection, items: list[NewsItem]) -> tuple[int, int]:
    inserted = 0
    duplicates = 0
    for item in items:
        if save_item(connection, item):
            inserted += 1
        else:
            duplicates += 1
    return inserted, duplicates


def count_items(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()
    return int(row["count"])
