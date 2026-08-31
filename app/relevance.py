from __future__ import annotations

import re

from .models import NewsItem

# Editorial scope: stories must fit one of these concrete robotics pillars.
# Generic mentions of "AI", "automation", autonomous vehicles, or drones are not enough.
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
        "industrial robot", "factory robot", "robotic arm", "robot arm", "robotic manipulator", "manipulator",
        "cobot", "collaborative robot", "welding robot", "palletizing robot", "pick-and-place",
        "machine tending", "manufacturing robot", "industrial robotics",
    ),
    "autonomous": (
        "autonomous robot", "autonomous robotics", "mobile robot", "amr", "autonomous mobile robot",
        "warehouse robot", "delivery robot", "logistics robot", "warehouse automation robot", "robot fleet",
        "autonomous forklift", "sorting robot", "fulfillment robot", "mobile manipulation robot",
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
        "robot locomotion", "locomotion for robots", "slam for robots",
    ),
}

# Explicit exclusions prevent the relevance layer from drifting into adjacent fields.
# Autonomous cars/trucks/taxis and drones are outside the publication's current seven pillars.
EXCLUDED_PATTERNS = (
    "robotaxi", "robotaxi", "autonomous taxi", "autonomous car", "autonomous vehicle",
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
    if any(pattern in text for pattern in EXCLUDED_PATTERNS):
        # Allow an article only when the excluded adjacent field is incidental and a
        # concrete in-scope robotics topic is clearly present.
        concrete_topics = classify(item)
        if not concrete_topics:
            return False
        robotics_signals = (
            "humanoid", "robot dog", "robotic dog", "quadruped", "exoskeleton", "robotic arm",
            "industrial robot", "warehouse robot", "mobile robot", "service robot", "medical robot",
            "surgical robot", "robot learning", "robot manipulation", "robot control", "robotics research",
        )
        if not any(signal in text for signal in robotics_signals):
            return False

    # A story must match a concrete editorial pillar. Generic "robot/robotics" mentions
    # are intentionally not sufficient, which removes adjacent autonomous-vehicle/drone noise.
    return bool(classify(item))


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
