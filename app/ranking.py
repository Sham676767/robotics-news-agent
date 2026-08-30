from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .models import NewsItem

# Conservative lexical signals. LLM ranking will be added later.
HIGH_VALUE_TERMS = {
    "humanoid": 5,
    "humanoid robot": 7,
    "robot dog": 6,
    "quadruped": 5,
    "exoskeleton": 6,
    "bipedal": 4,
    "robotics": 2,
    "robot": 1,
}

BREAKTHROUGH_TERMS = {
    "launch": 2,
    "unveil": 3,
    "unveils": 3,
    "debut": 3,
    "new": 1,
    "breakthrough": 5,
    "first": 3,
    "mass production": 5,
    "production": 2,
    "funding": 2,
    "acquisition": 2,
    "commercial": 3,
    "deployment": 3,
}

SOURCE_WEIGHTS = {
    "IEEE Spectrum Robotics": 1.0,
    "The Robot Report": 1.0,
    "Robotics & Automation News": 0.9,
    "Robohub": 0.9,
    "NVIDIA Robotics": 0.9,
}


def _text(item: NewsItem) -> str:
    return f"{item.title} {item.summary}".lower()


def _keyword_score(text: str, terms: dict[str, int]) -> float:
    score = 0
    for term, weight in terms.items():
        if term in text:
            score += weight
    return score


def _recency_score(published_at: datetime | None, now: datetime | None = None) -> float:
    if not published_at:
        return 0.0
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - published_at).total_seconds() / 3600)
    # Smooth decay: fresh stories receive more weight, old stories still survive.
    return 10.0 * math.exp(-hours / 48.0)


def score(item: NewsItem, now: datetime | None = None) -> float:
    text = _text(item)
    relevance = _keyword_score(text, HIGH_VALUE_TERMS)
    impact = _keyword_score(text, BREAKTHROUGH_TERMS)
    source = SOURCE_WEIGHTS.get(item.source, 0.6) * 10
    recency = _recency_score(item.published_at, now)
    # This is intentionally a pre-ranking heuristic, not the final viral score.
    return relevance * 3.0 + impact * 2.0 + source + recency


def rank(items: list[NewsItem], limit: int = 20, now: datetime | None = None) -> list[NewsItem]:
    return sorted(items, key=lambda item: score(item, now), reverse=True)[:limit]
