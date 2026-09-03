from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .models import NewsItem
from .relevance import classify

CATEGORY_WEIGHTS = {
    "humanoid": 9.0,
    "robot_dog": 8.0,
    "exoskeleton": 8.0,
    "robotics": 4.5,
    "research": 5.5,
    "industrial": 3.0,
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
    "gait": 2.0,
    "wearable robotics": 3.0,
    "powered exoskeleton": 3.0,
}

LOW_SIGNAL_TERMS = {
    "opinion": 3.0,
    "commentary": 2.0,
    "rumor": 6.0,
    "rumors": 6.0,
    "rumours": 6.0,
    "concept": 2.0,
}

EDITORIAL_NOISE_PATTERNS = (
    "top 10",
    "top 5",
    "best robotics stories",
    "robotics stories of",
    "weekly roundup",
    "monthly roundup",
    "weekly round-up",
    "monthly round-up",
    "news roundup",
    "news round-up",
    "robotics roundup",
    "robotics round-up",
    "this week in robotics",
    "this month in robotics",
    "month in review",
    "week in review",
    "what happened in",
    "what you missed",
)

PROMO_PATTERNS = (
    "learn why",
    "join us",
    "register now",
    "register for",
    "save your spot",
    "meet us at",
    "see us at",
    "visit us at",
    "at robobusiness",
    "at robobusiness",
    "conference session",
    "conference panel",
    "webinar",
    "fireside chat",
    "panel discussion",
    "speakers include",
)

# Research/community articles that discuss publishing, peer review or the
# research ecosystem rather than a concrete robot, capability or deployment.
RESEARCH_COMMENTARY_PATTERNS = (
    "paper deluge",
    "peer review",
    "publishing",
    "publication growth",
    "future of peer review",
    "research ecosystem",
    "research community",
    "panel on",
    "panel discussion",
    "conference panel",
    "notes from an icra panel",
)

# Useful for engineers, but usually too narrow to displace a mass-interest
# robotics story in a daily TOP-5. Keep these as eligible news, but strongly
# demote package/SDK/API/tooling releases unless they also describe a concrete
# robot deployment, breakthrough or major business event.
NICHE_TECHNICAL_PATTERNS = (
    "ros 2 package",
    "ros2 package",
    "ros 2 packages",
    "ros2 packages",
    "sdk release",
    "sdk releases",
    "api release",
    "api releases",
    "software package",
    "software packages",
    "driver release",
    "drivers release",
    "drop-in replacement",
    "controller interface",
    "python package",
)

AGGREGATOR_SOURCES = {
    "Google News Humanoid Robots",
    "Google News Robot Dogs",
    "Google News Exoskeletons",
    "Google News Robotics Research",
}

LOW_VALUE_DOMAINS = (
    "national law review",
    "law review",
    "legal",
)

SOURCE_WEIGHTS = {
    "The Robot Report": 1.00,
    "Robohub": 0.98,
    "TechCrunch Robotics": 0.98,
    "Tech Xplore Robotics": 0.96,
    "New Atlas Robotics": 0.90,
    "Robotiq": 0.88,
    "NVIDIA Robotics": 0.88,
    "RoboDK": 0.85,
    "Boston Dynamics": 0.82,
    "Clearpath Robotics": 0.82,
    "Google News Humanoid Robots": 0.72,
    "Google News Robot Dogs": 0.72,
    "Google News Exoskeletons": 0.72,
    "Google News Robotics Research": 0.72,
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
    return SOURCE_WEIGHTS.get(item.source, 0.70) * 5.0


def _title_bonus(item: NewsItem) -> float:
    title = item.title.lower()
    concrete = (
        "launch", "debut", "first", "record", "production", "deployment",
        "contract", "funding", "raised", "acquisition", "pilot", "ships", "shipped",
    )
    return min(sum(1.0 for term in concrete if term in title), 5.0)


def _editorial_noise_penalty(item: NewsItem) -> float:
    title = re.sub(r"\s+", " ", item.title.lower()).strip()
    summary = re.sub(r"\s+", " ", item.summary.lower()).strip()
    combined = f"{title} {summary}"
    penalty = 0.0

    for pattern in EDITORIAL_NOISE_PATTERNS:
        if pattern in title or pattern in summary:
            penalty += 18.0
            break

    promo_hits = sum(1 for pattern in PROMO_PATTERNS if pattern in combined)
    if promo_hits >= 2:
        penalty += 32.0
    elif promo_hits == 1:
        penalty += 18.0

    # Strongly demote research meta-discussion without a concrete robot/event.
    research_hits = sum(1 for pattern in RESEARCH_COMMENTARY_PATTERNS if pattern in combined)
    if research_hits >= 2:
        penalty += 30.0
    elif research_hits == 1 and not any(
        signal in combined
        for signal in ("robot", "humanoid", "quadruped", "exoskeleton", "deployment", "production", "launch")
    ):
        penalty += 22.0

    # Narrow developer-tooling releases are valid robotics news, but should not
    # routinely outrank consumer, deployment, business or breakthrough stories.
    niche_hits = sum(1 for pattern in NICHE_TECHNICAL_PATTERNS if pattern in combined)
    if niche_hits >= 2:
        penalty += 24.0
    elif niche_hits == 1:
        penalty += 16.0

    if item.source in AGGREGATOR_SOURCES:
        penalty += 7.0

    if any(term in combined for term in LOW_VALUE_DOMAINS):
        penalty += 10.0

    # Feed/parser artifacts often glue a publisher name onto the title.
    if title.count(" - ") >= 2 or title.count(" | ") >= 2:
        penalty += 5.0
    if len(title) > 150:
        penalty += 3.0

    return penalty


def _noise_penalty(item: NewsItem) -> float:
    text = _text(item)
    penalty = _keyword_score(text, LOW_SIGNAL_TERMS)
    if len(re.sub(r"\s+", " ", item.summary).strip()) < 80:
        penalty += 1.5
    if item.title.count("!") >= 2:
        penalty += 1.0
    return penalty + _editorial_noise_penalty(item)


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
