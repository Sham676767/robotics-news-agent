from __future__ import annotations

import re

from .models import NewsItem

# Editorial scope: the publication currently covers exactly four core topics.
# Generic mentions of AI, automation, autonomous vehicles, drones, or unrelated
# service/industrial robotics are not enough to enter the daily news pool.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "robotics": (
        "robotics", "robotic system", "robot technology", "robot technology", "robotics company",
        "robotics startup", "robotics research", "robotics lab", "robotics paper", "robotics study",
        "robot control", "robot learning", "robot manipulation", "robot perception", "robot navigation",
        "sim-to-real", "simulation-to-real", "imitation learning", "reinforcement learning",
        "vision-language-action", "vla model", "robot foundation model", "dexterous manipulation",
        "robot locomotion", "locomotion for robots", "slam for robots",
    ),
    "robot_dog": (
        "robot dog", "robotic dog", "quadruped", "robodog", "go2", "spot robot", "four-legged robot",
        "four legged robot", "quadruped robot", "robot dog platform",
    ),
    "humanoid": (
        "humanoid", "humanoid robot", "humanoid robotics", "android robot", "bipedal robot",
        "biped robot", "human-like robot", "humanlike robot", "humanoid platform",
    ),
    "exoskeleton": (
        "exoskeleton", "exo-skeleton", "powered suit", "wearable robot", "robotic exoskeleton",
        "powered exoskeleton", "assistive exoskeleton", "industrial exoskeleton", "medical exoskeleton",
    ),
}

# Adjacent fields are explicitly excluded unless the article is clearly about
# one of the four in-scope topics above.
EXCLUDED_PATTERNS = (
    "robotaxi", "autonomous taxi", "autonomous car", "autonomous vehicle",
    "autonomous truck", "self-driving truck", "self driving truck", "self-driving car",
    "self driving car", "autonomous driving", "self-driving", "self driving",
    "drone", "drones", "uav", "unmanned aerial vehicle",
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
    text = _normalized(f"{item.title} {item.summary}")
    topics = classify(item)

    # Never allow an adjacent autonomous-vehicle/drone story into the pool unless
    # the same story contains a strong, explicit signal for one of our four topics.
    if any(pattern in text for pattern in EXCLUDED_PATTERNS):
        if not topics:
            return False
        strong_signals = (
            "humanoid", "humanoid robot", "robot dog", "robotic dog", "quadruped",
            "exoskeleton", "robotic exoskeleton", "robotics research", "robotics lab",
            "robot learning", "robot manipulation", "robot control",
        )
        if not any(signal in text for signal in strong_signals):
            return False

    # A story must match at least one of the four concrete editorial topics.
    return bool(topics)


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
