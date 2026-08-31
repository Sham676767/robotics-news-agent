from __future__ import annotations
from typing import List, Dict
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ai_client import rank_with_deepseek
from .collector import collect_all
from .ranking import rank
from .relevance import classify, filter_relevant

OUTPUT_PATH = Path("data/latest_top5.json")

MAX_AGE = timedelta(days=14)
MAX_PER_SOURCE = 2
MIN_TOPIC_DIVERSITY = 3
CORE_TOPICS = ("humanoid", "robot_dog", "exoskeleton", "robotics")


def _recent(items: list) -> list:
    now = datetime.now(timezone.utc)
    result = []
    for item in items:
        published_at = item.published_at
        if not published_at:
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if now - published_at <= MAX_AGE:
            result.append(item)
    return result


def _diverse_ranked(items: list, limit: int = 12) -> list:
    ranked = rank(items, limit=max(limit * 3, 20))
    result = []
    per_source: dict[str, int] = {}
    for item in ranked:
        count = per_source.get(item.source, 0)
        if count >= MAX_PER_SOURCE:
            continue
        result.append(item)
        per_source[item.source] = count + 1
        if len(result) >= limit:
            break
    return result


def build_candidates(limit: int = 12, items: list | None = None) -> list[dict]:
    # Reuse the collection already performed by main.py. This avoids fetching
    # every RSS source twice in one workflow run.
    collected = items if items is not None else collect_all()
    relevant = filter_relevant(collected)
    recent = _recent(relevant)
    if len(recent) < 5:
        raise RuntimeError(
            f"Only {len(recent)} relevant stories are newer than {MAX_AGE.days} days; "
            "refusing to publish stale news"
        )
    ranked = _diverse_ranked(recent, limit=limit)
    return [
        {
            "id": index,
            "title": item.title,
            "source": item.source,
            "url": item.url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": item.summary[:1500],
            "topics": classify(item),
        }
        for index, item in enumerate(ranked, start=1)
    ]


def _topic_set(item: dict) -> set[str]:
    return set(item.get("topics") or ())


def _pick_result(candidate: dict, choice: dict | None = None, reason: str = "") -> dict:
    return {
        "rank": 0,
        "id": candidate["id"],
        "title": candidate["title"],
        "source": candidate["source"],
        "url": candidate["url"],
        "published_at": candidate["published_at"],
        "summary": candidate["summary"],
        "topics": candidate["topics"],
        "ai_score": choice.get("score") if choice else None,
        "why_selected": (choice.get("reason", "") if choice else reason),
    }


def _best_choice_for_topic(
    choices: list[tuple[dict, dict]], topic: str, used_ids: set[int], used_sources: set[str]
) -> tuple[dict, dict] | None:
    eligible = [
        pair for pair in choices
        if pair[1]["id"] not in used_ids and topic in _topic_set(pair[1])
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda pair: (
            pair[1]["source"] not in used_sources,
            float(pair[0].get("score") or 0),
        ),
    )


def select_top5(news=None) -> List[Dict]:
    candidates = build_candidates(items=news)

    # Ask AI for a larger ranked pool. We still publish only five stories, but
    # need enough candidates for the deterministic editorial coverage pass below.
    selected = rank_with_deepseek(candidates, limit=len(candidates))
    by_id = {item["id"]: item for item in candidates}

    result: list[dict] = []
    used_sources: set[str] = set()
    used_topics: set[str] = set()
    chosen_ids: set[int] = set()

    valid_choices: list[tuple[dict, dict]] = []
    for choice in selected:
        try:
            candidate_id = int(choice["id"])
        except (KeyError, TypeError, ValueError):
            continue
        candidate = by_id.get(candidate_id)
        if candidate:
            valid_choices.append((choice, candidate))

    # Pass 1: cover each core editorial pillar when the candidate pool contains it.
    for topic in CORE_TOPICS:
        picked = _best_choice_for_topic(valid_choices, topic, chosen_ids, used_sources)
        if not picked:
            continue
        choice, candidate = picked
        result.append(_pick_result(candidate, choice))
        chosen_ids.add(candidate["id"])
        used_sources.add(candidate["source"])
        used_topics.update(_topic_set(candidate))
        if len(result) >= 5:
            break

    # Pass 2: fill remaining slots from the AI ranking while preserving diversity.
    if len(result) < 5:
        for choice, candidate in valid_choices:
            if candidate["id"] in chosen_ids:
                continue
            source = candidate["source"]
            topics = _topic_set(candidate)
            if source in used_sources and len(used_sources) < 3:
                continue
            if topics and topics.issubset(used_topics) and len(used_topics) < MIN_TOPIC_DIVERSITY:
                continue
            result.append(_pick_result(candidate, choice))
            chosen_ids.add(candidate["id"])
            used_sources.add(source)
            used_topics.update(topics)
            if len(result) >= 5:
                break

    # Pass 3: deterministic fallback from the relevance/rank ordered pool.
    if len(result) < 5:
        for candidate in candidates:
            if candidate["id"] in chosen_ids:
                continue
            source = candidate["source"]
            if source in used_sources and len(used_sources) < 3:
                continue
            result.append(_pick_result(candidate, reason="Deterministic fallback from ranked candidates"))
            chosen_ids.add(candidate["id"])
            used_sources.add(source)
            used_topics.update(_topic_set(candidate))
            if len(result) >= 5:
                break

    if len(result) < 5:
        for candidate in candidates:
            if candidate["id"] in chosen_ids:
                continue
            result.append(_pick_result(candidate, reason="Final fallback from ranked candidates"))
            chosen_ids.add(candidate["id"])
            if len(result) >= 5:
                break

    for index, item in enumerate(result[:5], start=1):
        item["rank"] = index
    return result[:5]


def main() -> None:
    selected = select_top5()
    if len(selected) < 5:
        raise RuntimeError(f"Only {len(selected)} usable stories available; expected 5")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(selected)} stories")
    for item in selected:
        print(f"#{item['rank']} {item['title']} — {item['source']} — {', '.join(item['topics'])}")


if __name__ == "__main__":
    main()
