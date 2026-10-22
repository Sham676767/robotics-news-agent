"""Transparent usefulness ranking for business owners and potential legal clients."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.topics import Topic

# Stems describe client problems, not asserted rules of law.
SIGNALS = {
    "business": ("предпринимател", "бизнес", "договор", "контрагент", "налог", "банкрот", "субсидиар", "лицензи", "проверки", "штраф", "взыскан", "работодател", "аренд"),
    "legal_help": ("обжалован", "оспор", "защит", "спор", "компенсац", "ущерб", "увольнен", "наслед", "развод", "алименты", "недвижим", "кредит", "страхов", "задолжен", "потребител"),
}


@dataclass(frozen=True, slots=True)
class RankedTopic:
    topic: Topic
    score: float
    audience: tuple[str, ...]
    reasons: tuple[str, ...]


def is_fresh(topic: Topic, now: datetime, days: int) -> bool:
    date = topic.published_at
    if date is None:
        return False
    return now - timedelta(days=days) <= date <= now + timedelta(minutes=5)


def select_topics(topics: list[Topic], count: int, freshness_days: int, now: datetime | None = None) -> list[RankedTopic]:
    if count < 1 or freshness_days < 1:
        raise ValueError("count and freshness_days must be positive")
    now = now or datetime.now(timezone.utc)
    ranked = []
    for topic in topics:
        if not is_fresh(topic, now, freshness_days) or not any(ref.availability_verified for ref in topic.references):
            continue
        text = " ".join(f"{article.title} {article.text}" for article in topic.articles).casefold()
        matches = {audience: tuple(signal for signal in signals if signal in text) for audience, signals in SIGNALS.items()}
        audience = tuple(key for key, values in matches.items() if values)
        if not audience:
            continue
        usefulness = min(60, sum(len(values) for values in matches.values()) * 10)
        age = max(0, (now - topic.published_at).total_seconds() / 86400)  # type: ignore[operator]
        recency = 25 * max(0, 1 - age / freshness_days)
        score = usefulness + recency + 15
        reasons = tuple(f"{key}: {', '.join(values)}" for key, values in matches.items() if values)
        ranked.append(RankedTopic(topic, round(score, 2), audience, (*reasons, "Есть доступный прямой первоисточник и извлечённые реквизиты")))
    ranked.sort(key=lambda item: (-item.score, item.topic.id))
    return ranked[:count]
