from __future__ import annotations

import re

from .models import NewsItem

# The publication has exactly four editorial pillars. A story must contain an
# explicit signal for at least one pillar; generic AI/automation news is not enough.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "robotics": (
        "robotics", "robotic system", "robot technology", "robotics company",
        "robotics startup", "robotics research", "robotics lab", "robotics paper", "robotics study",
        "robot control", "robot learning", "robot manipulation", "robot perception", "robot navigation",
        "robot locomotion", "locomotion for robots", "sim-to-real", "simulation-to-real",
        "imitation learning", "reinforcement learning", "vision-language-action", "vla model",
        "robot foundation model", "dexterous manipulation", "slam for robots",
        "робототехника", "роботизированная система", "робототехническая компания",
        "управление роботом", "обучение роботов", "манипуляция роботом", "навигация робота",
    ),
    "robot_dog": (
        "robot dog", "robotic dog", "quadruped", "robodog", "go2", "spot robot",
        "four-legged robot", "four legged robot", "quadruped robot", "robot dog platform",
        "робот-собака", "робот собака", "робопёс", "робопес", "четвероногий робот",
    ),
    "humanoid": (
        "humanoid", "humanoid robot", "humanoid robotics", "android robot", "bipedal robot",
        "biped robot", "human-like robot", "humanlike robot", "humanoid platform",
        "гуманоид", "гуманоидный робот", "человекоподобный робот", "двуногий робот",
    ),
    "exoskeleton": (
        "exoskeleton", "exo-skeleton", "powered suit", "wearable robot", "robotic exoskeleton",
        "powered exoskeleton", "assistive exoskeleton", "industrial exoskeleton", "medical exoskeleton",
        "экзоскелет", "роботизированный экзоскелет", "силовой костюм", "носимый робот",
    ),
}

# Adjacent fields are excluded unless the same story also has a strong explicit
# signal for one of the four editorial pillars.
EXCLUDED_PATTERNS = (
    "robotaxi", "autonomous taxi", "autonomous car", "autonomous vehicle",
    "autonomous truck", "self-driving truck", "self driving truck", "self-driving car",
    "self driving car", "autonomous driving", "self-driving", "self driving",
    "drone", "drones", "uav", "unmanned aerial vehicle",
    "роботакси", "беспилотный автомобиль", "автономный автомобиль", "дрон", "дроны",
)

STRONG_SIGNALS = (
    "humanoid", "humanoid robot", "robot dog", "robotic dog", "quadruped",
    "exoskeleton", "robotic exoskeleton", "robotics research", "robotics lab",
    "robot learning", "robot manipulation", "robot control", "гуманоид",
    "гуманоидный робот", "робот-собака", "робопёс", "робопес", "экзоскелет",
    "робототехника", "роботизированная система", "роботизированный экзоскелет",
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

    if any(pattern in text for pattern in EXCLUDED_PATTERNS):
        return any(signal in text for signal in STRONG_SIGNALS)

    return bool(topics)


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
