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
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text


def _russian_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 1.0
    cyrillic = sum("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in letters)
    return cyrillic / len(letters)


def _topics(item: dict[str, Any]) -> str:
    labels = [TOPIC_LABELS.get(str(topic), str(topic)) for topic in item.get("topics") or []]
    return ", ".join(dict.fromkeys(labels)) or "робототехника"


def _is_acceptable_russian_card(item: dict[str, Any]) -> bool:
    title = _clean_text(item.get("title", ""))
    summary = _clean_text(item.get("summary", ""))
    return _russian_ratio(f"{title} {summary}") >= 0.55


def generate_fallback_article(top5: list[dict[str, Any]]) -> dict[str, Any]:
    if len(top5) != 5:
        raise ValueError("Fallback article requires exactly 5 stories")

    # A deterministic fallback may keep the pipeline alive, but it must never
    # publish raw English source text as a supposed Russian editorial article.
    bad_cards = [item for item in top5 if not _is_acceptable_russian_card(item)]
    if bad_cards:
        raise RuntimeError(
            "AI article generation is unavailable and the selected source cards "
            "are not sufficiently Russian for a safe fallback article"
        )

    topic_names = []
    for item in top5:
        topic_names.extend([TOPIC_LABELS.get(str(t), str(t)) for t in item.get("topics") or []])
    topic_names = list(dict.fromkeys(topic_names))
    coverage = ", ".join(topic_names[:4]) or "робототехника"

    result = {
        "title": "Робототехника недели: главные события в гуманоидных роботах, робо-собаках и экзоскелетах",
        "intro": (
            "В подборку вошли пять свежих событий из мира робототехники. "
            f"Основные направления выпуска — {coverage}. "
            "Ниже приведены только сведения, присутствующие в исходных карточках новостей."
        ),
        "items": [],
    }

    for item in top5:
        title = _clean_text(item.get("title")) or "Событие в робототехнике"
        summary = _clean_text(item.get("summary")) or "Источник не содержит дополнительного краткого описания."
        topics = _topics(item)
        source = _clean_text(item.get("source")) or "Источник"
        body = (
            f"{summary.rstrip('.!?…')}. "
            f"Материал относится к направлению {topics}. "
            "Дополнительные сведения о характеристиках, масштабах внедрения или результате события "
            "не добавляются без подтверждения в исходной новости."
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
