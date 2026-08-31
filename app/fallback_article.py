from __future__ import annotations

import re
from typing import Any

TOPIC_LABELS = {
    "humanoid": "гуманоидные роботы",
    "robot_dog": "роботы-собаки",
    "exoskeleton": "экзоскелеты",
    "robotics": "робототехника",
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _topics(item: dict[str, Any]) -> str:
    labels = [TOPIC_LABELS.get(str(topic), str(topic)) for topic in item.get("topics") or []]
    return ", ".join(dict.fromkeys(labels)) or "робототехника"


def generate_fallback_article(top5: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate a safe article without an LLM.

    Source cards may be English. The fallback therefore does not reject cards
    based on language and never invents facts beyond title, summary and topic.
    """
    if len(top5) != 5:
        raise ValueError("Fallback article requires exactly 5 stories")

    topic_names = []
    for item in top5:
        topic_names.extend(
            TOPIC_LABELS.get(str(topic), str(topic))
            for topic in item.get("topics") or []
        )
    coverage = ", ".join(dict.fromkeys(topic_names)) or "робототехника"

    result = {
        "title": "Робототехника недели: главные события и новые разработки",
        "intro": (
            "В подборку вошли пять свежих событий из мира робототехники. "
            f"Основные направления выпуска — {coverage}. "
            "В резервном режиме используются только сведения из исходных карточек новостей."
        ),
        "items": [],
    }

    for item in top5:
        title = _clean_text(item.get("title")) or "Событие в робототехнике"
        summary = _clean_text(item.get("summary"))
        topics = _topics(item)
        source = _clean_text(item.get("source")) or "Источник"
        if summary:
            body = (
                f"{summary.rstrip('.!?…')}. "
                f"Материал относится к направлению {topics}. "
                "Дополнительные характеристики и выводы без подтверждения в исходной новости не добавляются."
            )
        else:
            body = (
                f"Источник сообщает о событии «{title}». "
                f"Материал относится к направлению {topics}."
            )
        result["items"].append({
            "headline": title,
            "body": body,
            "source": source,
            "url": item["url"],
        })

    return result
