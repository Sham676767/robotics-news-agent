from __future__ import annotations

import re

from .models import NewsItem

# Strong signals that identify an actual robotics story.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "humanoid": (
        "humanoid",
        "humanoid robot",
        "android robot",
        "bipedal robot",
        "biped robot",
    ),
    "robot_dog": (
        "robot dog",
        "robotic dog",
        "quadruped",
        "robodog",
        "go2",
        "spot robot",
    ),
    "exoskeleton": (
        "exoskeleton",
        "exo-skeleton",
        "powered suit",
        "wearable robot",
        "robotic exoskeleton",
    ),
    "industrial": (
        "industrial robot",
        "factory robot",
        "robotic arm",
        "robot arm",
        "manipulator",
        "cobot",
        "collaborative robot",
    ),
    "autonomous": (
        "autonomous robot",
        "autonomous robotics",
        "mobile robot",
        "amr",
        "autonomous mobile robot",
        "warehouse robot",
        "delivery robot",
    ),
    "service": (
        "service robot",
        "robotic assistant",
        "medical robot",
        "surgical robot",
        "rehabilitation robot",
        "hospital robot",
    ),
    "research": (
        "robotics research",
        "robotics lab",
        "robot learning",
        "robot manipulation",
        "robot perception",
        "robot navigation",
        "robot control",
    ),
    "robotics": (
        "robotics",
        "robotic",
        "robot",
        "robotics company",
        "robotics startup",
    ),
}

# Context terms are useful only together with a concrete robotics signal.
CONTEXT_TERMS = (
    "automation",
    "autonomous",
    "artificial intelligence",
    "physical ai",
    "manufacturing",
    "warehouse",
    "factory",
    "mobility",
    "computer vision",
    "reinforcement learning",
)


def _normalized(text: str) -> str:
    text = text.lower().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def classify(item: NewsItem) -> tuple[str, ...]:
    text = _normalized(f"{item.title} {item.summary}")
    matches: list[str] = []
    for topic, words in KEYWORDS.items():
        if any(word in text for word in words):
            matches.append(topic)
    return tuple(matches)


def is_relevant(item: NewsItem) -> bool:
    topics = classify(item)
    if not topics:
        return False

    # Specific robotics categories are strong enough on their own.
    if set(topics) - {"robotics"}:
        return True

    # A generic mention of "robot" is accepted only when the article also
    # contains robotics/automation context. This reduces accidental matches.
    text = _normalized(f"{item.title} {item.summary}")
    return any(term in text for term in CONTEXT_TERMS)


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
