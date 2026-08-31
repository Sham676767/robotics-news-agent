from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .models import NewsItem
from .relevance import classify

# Conservative pre-ranking: prioritize concrete robotics significance before
# freshness and source reputation. Final TOP-5 selection remains AI-assisted.
CATEGORY_WEIGHTS = {
    "humanoid": 8.0,
    "robot_dog": 6.5,
    "exoskeleton": 6.5,
    "industrial": 6.0,
    "autonomous": 6.0,
    "service": 5.5,
    "research": 5.5,
    "robotics": 2.0,
}

IMPACT_SIGNALS = {
    "mass production": 8.0,
    "mass-produced": 8.0,
    "commercial deployment": 7.0,
    "deployment": 5.0,
    "deployed": 5.0,
    "production": 4.5,
    "pilot": 3.5,
    "funding": 4.0,
    "raised": 4.0,
    "investment": 4.0,
    "acquisition": 4.0,
    "partnership": 2.5,
    "contract": 3.5,
    "order": 3.5,
    "first": 3.0,
    "record": 2.5,
    "launch": 2.5,
    "unveil": 2.5,
    "unveils": 2.5,
    "debut": 2.5,
    "paper": 2.0,
}

TECHNICAL_SIGNALS = {
    "manipulation": 2.5,
    "locomotion": 2.5,
    "navigation": 2.0,
    "perception": 2.0,
    "reinforcement learning": 2.5,
    "vision-language-action": 3.0,
    "vla": 2.5,
    "physical ai": 3.0,
    "autonomy": 2.0,
    "actuator": 2.0,
    "gripper": 1.5,
    "dexterity": 2.5,
    "computer vision": 1.5,
}

LOW_SIGNAL_TERMS = {
    "opinion": 3.0,
    "commentary": 2.0,
    "rumor": 6.0,
    "rumors": 6.0,
    "rumours": 6.0,
    "concept": 2.0,
}

SOURCE_WEIGHTS = {
    "IEEE Spectrum Robotics": 1.00,
    "The Robot Report": 1.00,
    "Robotics & Automation News": 0.95,
    "Robohub": 0.95,
    "NVIDIA Robotics": 0.90,
}


def _text(item: NewsItem) -> str:
    return f"{item.title} {item.summary}".lower()


def _keyword_score(text: str, terms: dict[str, float]) -> float:
    return sum(weight for term, weight in terms.items() if term in text)


def _recency_score(published_at: datetime | None, now: datetime | None = None) -> float:
    if not published_at:
        return 0.0
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - published_at).total_seconds() / 3600)
    return 12.0 * math.exp(-hours / 72.0)


def _category_score(item: NewsItem) -> float:
    detected = set(classify(item))
    configured = set(item.topics)
    categories = detected | configured
    return max((CATEGORY_WEIGHTS.get(category, 0.0) for category in categories), default=0.0)


def _source_score(item: NewsItem) -> float:
    # Source reputation is only a modest tie-breaker.
    return SOURCE_WEIGHTS.get(item.source, 0.70) * 5.0


def _title_bonus(item: NewsItem) -> float:
    title = item.title.lower()
    concrete = (
        "launch", "debut", "first", "record", "production", "deployment",
        "contract", "funding", "raised", "acquisition", "pilot", "ships", "shipped",
    )
    return min(sum(1.0 for term in concrete if term in title), 5.0)


def _noise_penalty(item: NewsItem) -> float:
    text = _text(item)
    penalty = _keyword_score(text, LOW_SIGNAL_TERMS)
    if len(re.sub(r"\s+", " ", item.summary).strip()) < 80:
        penalty += 1.5
    if item.title.count("!") >= 2:
        penalty += 1.0
    return penalty


def score(item: NewsItem, now: datetime | None = None) -> float:
    text = _text(item)
    category = _category_score(item)
    impact = _keyword_score(text, IMPACT_SIGNALS)
    technical = _keyword_score(text, TECHNICAL_SIGNALS)
    source = _source_score(item)
    recency = _recency_score(item.published_at, now)
    title_bonus = _title_bonus(item)
    noise = _noise_penalty(item)

    return (
        category * 3.0
        + impact * 2.2
        + technical * 1.5
        + title_bonus
        + source
        + recency
        - noise * 2.0
    )


def rank(items: list[NewsItem], limit: int = 20, now: datetime | None = None) -> list[NewsItem]:
    return sorted(items, key=lambda item: score(item, now), reverse=True)[:limit]
