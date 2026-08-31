from __future__ import annotations

import re

from .models import NewsItem

# The publication has exactly four editorial pillars. Generic AI/automation
# stories are not enough: the text must explicitly concern robots/robotics,
# robot dogs, humanoids, or exoskeletons.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "robotics": (
        "robotics", "robotic system", "robot technology", "robotics company",
        "robotics startup", "robotics research", "robotics lab", "robotics paper",
        "robotics study", "robot control", "robot learning", "robot manipulation",
        "robot perception", "robot navigation", "robot locomotion", "locomotion for robots",
        "sim-to-real", "simulation-to-real", "robot foundation model", "dexterous manipulation",
        "slam for robots", "robot arm", "robotic arm", "industrial robot", "service robot",
        "mobile robot", "warehouse robot", "collaborative robot", "cobot",
        "робототехника", "роботизированная система", "робототехническая компания",
        "управление роботом", "обучение роботов", "манипуляция роботом", "навигация робота",
        "промышленный робот", "сервисный робот", "мобильный робот", "робот-манипулятор",
        "роботизированная рука", "коллаборативный робот",
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

# Adjacent fields are excluded unless the same story explicitly contains one
# of the four pillars. This prevents drone/robotaxi stories from leaking in
# just because they mention generic robotics or AI research.
EXCLUDED_PATTERNS = (
    "robotaxi", "autonomous taxi", "autonomous car", "autonomous vehicle",
    "autonomous truck", "self-driving truck", "self driving truck", "self-driving car",
    "self driving car", "autonomous driving", "self-driving", "self driving",
    "drone", "drones", "uav", "unmanned aerial vehicle",
    "роботакси", "беспилотный автомобиль", "автономный автомобиль", "дрон", "дроны",
)

SPECIFIC_PILLAR_SIGNALS = (
    "humanoid", "humanoid robot", "robot dog", "robotic dog", "quadruped",
    "robodog", "four-legged robot", "four legged robot", "exoskeleton",
    "exo-skeleton", "robotic exoskeleton", "powered exoskeleton", "wearable robot",
    "экзоскелет", "роботизированный экзоскелет", "силовой костюм", "носимый робот",
    "гуманоид", "гуманоидный робот", "человекоподобный робот", "двуногий робот",
    "робот-собака", "робот собака", "робопёс", "робопес", "четвероногий робот",
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
        return any(signal in text for signal in SPECIFIC_PILLAR_SIGNALS)

    return bool(topics)


def filter_relevant(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if is_relevant(item)]
