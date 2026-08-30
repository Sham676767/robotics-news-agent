from __future__ import annotations

import re
from .models import NewsItem

# Conservative first-pass filter. LLM classification will be added later.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "humanoid": ("humanoid", "android robot", "bipedal robot", "humanoid robot"),
    "robot_dog": ("robot dog", "robotic dog", "quadruped", "robodog", "go2", "spot"),
    "exoskeleton": ("exoskeleton", "exo-skeleton", "powered suit", "wearable robot"),
    "robotics": ("robotics", "robot", "robotic", "robot arm", "manipulator", "autonomous robot"),
}


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def classify(item: NewsItem) -> tuple[str, ...]:
    text = _normalized(f"{item.title} {item.summary}")
    matches: list[str] = []
    for topic, words in KEYWORDS.items():
        if any(word in text for word in words):
            matches.append(topic)
    return tuple(matches)


def is_relevant(item: NewsItem) -> bool:
    return bool(classify(item))


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
