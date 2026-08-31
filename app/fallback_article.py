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


def _one_sentence(text: str) -> str:
    """Keep source wording compact so the fallback has predictable sentence count."""
    cleaned = _clean_text(text)
    cleaned = re.sub(r"[.!?…]+", " ", cleaned)
    return _clean_text(cleaned).rstrip(".,;:")


def _language_ratio(text: str) -> float:
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    letters = cyrillic + latin
    return cyrillic / letters if letters else 0.0


def _topics(item: dict[str, Any]) -> str:
    labels = [TOPIC_LABELS.get(str(topic), str(topic)) for topic in item.get("topics") or []]
    return ", ".join(dict.fromkeys(labels)) or "робототехника"


def generate_fallback_article(top5: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate a safe article without an LLM using only source-card facts."""
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

    for card_index, item in enumerate(top5, start=1):
        title = _clean_text(item.get("title")) or "Событие в робототехнике"
        summary = _one_sentence(item.get("summary"))
        topics = _topics(item)

        # Source cards may contain English summaries. Do not copy a predominantly
        # English summary into Russian editorial prose when the LLM is unavailable.
        # The headline remains the exact source title, while the body stays safe
        # and Russian instead of failing the publication language guard.
        if summary and _language_ratio(summary) >= 0.45:
            first_sentence = f"{summary}."
        else:
            first_sentence = "В исходной карточке описано событие в сфере робототехники."

        body = (
            f"{first_sentence} "
            f"Материал относится к направлению {topics}. "
            "Дополнительные характеристики и выводы без подтверждения в исходной новости не добавляются."
        )

        result["items"].append({
            "headline": title,
            "body": body,
            "card_index": card_index,
        })

    return result
