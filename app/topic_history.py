"""SQLite snapshots and explicit, transactional confirmation of used topics."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from app.topics import Topic, topic_from_dict, topic_to_dict


class TopicHistory:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS topics (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, collected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS used_topics (
                topic_id TEXT PRIMARY KEY REFERENCES topics(id), used_at TEXT NOT NULL
            );
        ''')

    def __enter__(self) -> TopicHistory:
        return self

    def __exit__(self, *args: object) -> None:
        self.connection.close()

    def save_selected(self, topics: Sequence[Topic]) -> None:
        with self.connection:
            for topic in topics:
                # Never change the content of an already-used historical snapshot.
                self.connection.execute('''
                    INSERT INTO topics VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, collected_at=excluded.collected_at
                    WHERE NOT EXISTS (SELECT 1 FROM used_topics WHERE topic_id=excluded.id)
                ''', (topic.id, json.dumps(topic_to_dict(topic), ensure_ascii=False), datetime.now(timezone.utc).isoformat()))

    def used_topics(self) -> list[Topic]:
        rows = self.connection.execute("SELECT payload FROM topics JOIN used_topics ON topics.id=used_topics.topic_id ORDER BY used_at, topics.id")
        return [topic_from_dict(json.loads(row[0])) for row in rows]

    def mark_used(self, ids: Sequence[str]) -> int:
        ids = list(dict.fromkeys(ids))
        if not ids:
            raise ValueError("At least one topic id is required")
        for topic_id in ids:
            if self.connection.execute("SELECT 1 FROM topics WHERE id=?", (topic_id,)).fetchone() is None:
                raise ValueError(f"Unknown collected topic id: {topic_id}")
        changed = 0
        with self.connection:
            for topic_id in ids:
                cursor = self.connection.execute("INSERT OR IGNORE INTO used_topics VALUES (?, ?)",
                                                 (topic_id, datetime.now(timezone.utc).isoformat()))
                changed += cursor.rowcount
        return changed
