from __future__ import annotations

import re

from .models import NewsItem

# Seven editorial pillars used by the robotics publication.
# A story may belong to more than one pillar; this is useful for later ranking.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "humanoid": (
        "humanoid", "humanoid robot", "android robot", "bipedal robot", "biped robot",
        "human-like robot", "humanoid robotics",
    ),
    "robot_dog": (
        "robot dog", "robotic dog", "quadruped", "robodog", "go2", "spot robot", "four-legged robot",
    ),
    "exoskeleton": (
        "exoskeleton", "exo-skeleton", "powered suit", "wearable robot", "robotic exoskeleton",
        "powered exoskeleton", "assistive exoskeleton",
    ),
    "industrial": (
        "industrial robot", "factory robot", "robotic arm", "robot arm", "manipulator", "cobot",
        "collaborative robot", "welding robot", "palletizing robot", "pick-and-place", "machine tending",
        "manufacturing robot",
    ),
    "autonomous": (
        "autonomous robot", "autonomous robotics", "mobile robot", "amr", "autonomous mobile robot",
        "warehouse robot", "delivery robot", "logistics robot", "warehouse automation", "robot fleet",
        "autonomous forklift", "sorting robot", "fulfillment robot",
    ),
    "service": (
        "service robot", "robotic assistant", "medical robot", "surgical robot", "rehabilitation robot",
        "hospital robot", "healthcare robot", "care robot", "social robot", "cleaning robot",
        "hospitality robot", "assistive robot",
    ),
    "research": (
        "robotics research", "robotics lab", "robot learning", "robot manipulation", "robot perception",
        "robot navigation", "robot control", "robotics paper", "robotics study", "sim-to-real",
        "simulation-to-real", "imitation learning", "reinforcement learning", "vision-language-action",
        "vla model", "robot foundation model", "robot foundation models", "dexterous manipulation",
        "locomotion", "slam for robots",
    ),
    "robotics": (
        "robotics", "robotic", "robot", "robotics company", "robotics startup", "robot maker",
        "robot manufacturer",
    ),
}

# Generic context is accepted only together with a concrete robotics signal.
CONTEXT_TERMS = (
    "automation", "autonomous", "artificial intelligence", "physical ai", "embodied ai",
    "manufacturing", "warehouse", "factory", "mobility", "computer vision", "robot learning",
    "robot control", "robot manipulation", "robot navigation", "robot perception",
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

    # Any specific pillar is enough to qualify a robotics story.
    if set(topics) - {"robotics"}:
        return True

    # A generic mention of "robot" needs supporting technical/industry context.
    text = _normalized(f"{item.title} {item.summary}")
    return any(term in text for term in CONTEXT_TERMS)


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
