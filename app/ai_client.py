from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from app.gigachat_client import GigaChatError, request_completion

DEFAULT_MODEL = "GigaChat"
DEFAULT_TIMEOUT = 35.0

CORE_TOPICS = ("humanoid", "robot_dog", "exoskeleton", "robotics")
TOPIC_PRIORITY = {"humanoid": 4, "robot_dog": 4, "exoskeleton": 4, "robotics": 2}


def build_ranking_prompt(items: list[dict[str, Any]], limit: int = 5) -> str:
    compact = [
        {
            "id": i["id"],
            "title": i["title"],
            "source": i["source"],
            "published_at": i.get("published_at"),
            "summary": i.get("summary", "")[:1200],
            "topics": i.get("topics", []),
        }
        for i in items
    ]
    return (
        "Ты редактор новостного проекта, посвящённого только четырём направлениям: "
        "1) робототехника, 2) роботы-собаки, 3) гуманоидные роботы, 4) экзоскелеты. "
        f"Ранжируй до {limit} самых интересных событий из переданных карточек. "
        "Карточки уже прошли тематический фильтр. Не добавляй внешние истории и не меняй id. "
        "Особенно повышай приоритет новостей, где явно указаны humanoid, robot dog/quadruped или exoskeleton. "
        "Новости про robotaxi, автомобили, дроны и другую тематику не должны получать приоритет, "
        "если они не являются частью одной из четырёх тем. Не придумывай факты. "
        "Оценивай новизну, общественный интерес, технологическую значимость, свежесть и качество источника. "
        "Верни только JSON-объект вида {"ranking": [{"id": 1, "score": 0, "reason": "..."}]}.\n\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"AI did not return parseable JSON: {text[:500]!r}")


FALLBACK_AGGREGATOR_MARKERS = ("google news", "feedly", "yahoo news", "msn")
FALLBACK_PROMO_MARKERS = (
    "partner", "partnership", "platform to encourage", "initiative", "discusses",
    "market hurdles", "market outlook", "market discussion", "industry outlook",
    "webinar", "panel discussion", "conference session", "register now",
)
FALLBACK_CONCRETE_MARKERS = (
    "launch", "launched", "unveil", "unveiled", "debut", "deploy", "deployed",
    "deployment", "production", "pilot", "contract", "funding", "raised",
    "investment", "acquisition", "order", "ships", "shipped", "delivered",
    "demonstrates", "demonstrated", "prototype", "study finds", "researchers",
    "learns", "record", "first",
)
FALLBACK_RESEARCH_META_MARKERS = (
    "peer review", "research ecosystem", "publication growth", "paper deluge",
    "future of peer review", "research community",
)


def _fallback_age_hours(value: Any, now: datetime) -> float | None:
    if not value:
        return None
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return max(0.0, (now - published).total_seconds() / 3600)


def _heuristic_fallback(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Rank locally by editorial value when the remote ranker is unavailable.

    This intentionally favours a recent, concrete primary-source story over an
    older or generic item with a more specific topic label.
    """
    now = datetime.now(timezone.utc)

    def fallback_score(item: dict[str, Any]) -> float:
        topics = set(item.get("topics") or ())
        text = f'{item.get("title", "")} {item.get("summary", "")}'.lower()
        source = str(item.get("source", "")).lower()
        score = max((TOPIC_PRIORITY.get(topic, 0) for topic in topics), default=0) * 4.0
        score += min(sum(TOPIC_PRIORITY.get(topic, 0) for topic in topics), 8) * 1.25

        age = _fallback_age_hours(item.get("published_at"), now)
        if age is None:
            score -= 7.0
        elif age <= 24:
            score += 24.0
        elif age <= 72:
            score += 17.0
        elif age <= 120:
            score += 6.0
        elif age <= 168:
            score -= 10.0
        else:
            score -= 24.0

        concrete_hits = sum(marker in text for marker in FALLBACK_CONCRETE_MARKERS)
        promo_hits = sum(marker in text for marker in FALLBACK_PROMO_MARKERS)
        score += min(concrete_hits, 3) * 6.0
        if promo_hits and not concrete_hits:
            score -= 30.0 + min(promo_hits - 1, 2) * 8.0
        if any(marker in text for marker in FALLBACK_RESEARCH_META_MARKERS):
            score -= 24.0
        if any(marker in source for marker in FALLBACK_AGGREGATOR_MARKERS):
            score -= 22.0
        if len(str(item.get("summary", "")).strip()) < 90:
            score -= 3.0
        return score

    ranked = sorted(items, key=lambda item: (fallback_score(item), str(item.get("published_at") or "")), reverse=True)
    return [
        {
            "id": item["id"],
            "score": round(fallback_score(item), 2),
            "reason": "AI ranking unavailable; deterministic freshness-and-event fallback",
        }
        for item in ranked[:limit]
    ]


def _normalise_ai_ranking(result: Any, items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep only unique, known candidate IDs and fill missing slots deterministically."""
    if not isinstance(result, list):
        raise ValueError("AI returned non-list JSON")

    known_ids = {item["id"] for item in items}
    seen: set[int] = set()
    valid: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            candidate_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if candidate_id not in known_ids or candidate_id in seen:
            continue
        seen.add(candidate_id)
        valid.append({
            "id": candidate_id,
            "score": item.get("score", 0),
            "reason": str(item.get("reason", ""))[:500],
        })
        if len(valid) >= limit:
            break

    if not valid:
        raise ValueError("AI returned no usable ranking items")

    if len(valid) < limit:
        fallback = _heuristic_fallback(
            [item for item in items if item["id"] not in seen],
            limit=limit - len(valid),
        )
        valid.extend(fallback)
    return valid[:limit]


RANKING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ranking"],
    "properties": {
        "ranking": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "score", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


def rank_with_gigachat(
    items: list[dict[str, Any]],
    credentials: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Ask GigaChat to rank candidates, with the deterministic fallback intact."""
    key = credentials or os.getenv("GIGACHAT_AUTHORIZATION_KEY")
    if not items:
        return []
    limit = max(1, min(limit, len(items)))
    if not key:
        print("Warning: GIGACHAT_AUTHORIZATION_KEY is not configured; using deterministic ranking fallback.")
        return _heuristic_fallback(items, limit=limit)

    payload = {
        "model": os.getenv("GIGACHAT_MODEL", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": "Отвечай только валидным JSON без markdown и пояснений."},
            {"role": "user", "content": build_ranking_prompt(items, limit=limit)},
        ],
        "temperature": 0.1,
        "max_tokens": max(1200, limit * 220),
        "response_format": {
            "type": "json_schema",
            "schema": RANKING_SCHEMA,
            "strict": True,
        },
    }
    timeout = float(os.getenv("GIGACHAT_RANK_TIMEOUT", str(DEFAULT_TIMEOUT)))
    try:
        data = request_completion(payload, credentials=key, timeout=timeout)
        choices = data.get("choices") or []
        if not choices:
            raise GigaChatError(
                f"GigaChat returned no ranking choices: {json.dumps(data, ensure_ascii=False)[:1000]}"
            )
        content = (choices[0].get("message") or {}).get("content")
        result = _extract_json(content)
        if isinstance(result, dict):
            result = result.get("ranking")
        return _normalise_ai_ranking(result, items, limit)
    except (GigaChatError, ValueError, RuntimeError) as exc:
        print(f"Warning: GigaChat ranking unavailable: {exc}; using deterministic ranking fallback.")
        return _heuristic_fallback(items, limit=limit)


def rank_with_deepseek(
    items: list[dict[str, Any]],
    api_key: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Compatibility alias for callers from earlier pipeline versions."""
    return rank_with_gigachat(items, credentials=api_key, limit=limit)
