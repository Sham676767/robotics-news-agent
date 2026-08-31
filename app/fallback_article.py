from __future__ import annotations

import re
from typing import Any

TOPIC_LABELS = {
    "humanoid": "гуманоидные роботы",
    "robot_dog": "роботы-собаки",
    "exoskeleton": "экзоскелеты",
    "robotics": "общая робототехника",
}


def _clean_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return "Источник содержит краткое описание события без дополнительных деталей."
    return text.rstrip(".!?…") + "."


def _topics(item: dict[str, Any]) -> str:
    labels = [TOPIC_LABELS.get(str(topic), str(topic)) for topic in item.get("topics") or []]
    return ", ".join(dict.fromkeys(labels)) or "робототехника"


def generate_fallback_article(top5: list[dict[str, Any]]) -> dict[str, Any]:
    if len(top5) != 5:
        raise ValueError("Fallback article requires exactly 5 stories")

    topic_names = []
    for item in top5:
        topic_names.extend([TOPIC_LABELS.get(str(t), str(t)) for t in item.get("topics") or []])
    topic_names = list(dict.fromkeys(topic_names))
    coverage = ", ".join(topic_names[:4]) or "робототехника"

    result = {
        "title": "Робототехника недели: главные события и новые разработки",
        "intro": (
            "В подборку вошли пять свежих событий из мира робототехники. "
            f"Новости охватывают такие направления, как {coverage}. "
            "Ниже — краткое изложение фактов по каждому выбранному материалу."
        ),
        "items": [],
    }

    for index, item in enumerate(top5, start=1):
        title = str(item.get("title") or "Событие в робототехнике").strip()
        summary = _clean_summary(item.get("summary", ""))
        topics = _topics(item)
        source = str(item.get("source") or "Источник")
        body = (
            f"{title}. "
            f"{summary} "
            f"Материал относится к направлению {topics}; дополнительные выводы о технологической или коммерческой зрелости без данных источника делать не следует."
        )
        result["items"].append(
            {
                "headline": title,
                "body": body,
                "source": source,
                "url": item["url"],
            }
        )

    return result
