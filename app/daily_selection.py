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
CORE_TOPICS = ("humanoid", "robot_dog", "exoskeleton", "robotics")
SPECIFIC_TOPICS = ("humanoid", "robot_dog", "exoskeleton")


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


def _dedupe(items: list) -> list:
    """Remove duplicate URLs before ranking so syndicated stories do not crowd TOP-5."""
    seen: set[str] = set()
    result = []
    for item in items:
        url = (item.url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _diverse_ranked(items: list, limit: int = 12) -> list:
    ranked = rank(items, limit=max(limit * 3, 20))
    result = []
    per_source: dict[str, int] = {}
    covered_specific: set[str] = set()

    for item in ranked:
        if len(result) >= limit:
            break
        count = per_source.get(item.source, 0)
        if count >= MAX_PER_SOURCE:
            continue
        topics = set(classify(item))
        new_specific = topics.intersection(SPECIFIC_TOPICS) - covered_specific
        if not new_specific:
            continue
        result.append(item)
        per_source[item.source] = count + 1
        covered_specific.update(new_specific)

    selected_urls = {item.url for item in result}
    for item in ranked:
        if len(result) >= limit:
            break
        if item.url in selected_urls:
            continue
        count = per_source.get(item.source, 0)
        if count >= MAX_PER_SOURCE:
            continue
        result.append(item)
        per_source[item.source] = count + 1
        selected_urls.add(item.url)

    return result


def build_candidates(limit: int = 12, items: list | None = None) -> list[dict]:
    collected = items if items is not None else collect_all()
    relevant = filter_relevant(collected)
    recent = _dedupe(_recent(relevant))
    if len(recent) < 5:
        raise RuntimeError(
            f"Only {len(recent)} relevant stories are newer than {MAX_AGE.days} days; refusing to publish stale news"
        )
    ranked = _diverse_ranked(recent, limit=limit)
    if len(ranked) < 5:
        raise RuntimeError(
            f"Only {len(ranked)} unique candidates remain after source/topic diversity filtering; expected at least 5"
        )
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


def _score_coverage(candidate: dict, choice: dict, covered_topics: set[str], used_sources: set[str]) -> tuple[float, ...]:
    topics = _topic_set(candidate)
    uncovered_specific = topics.intersection(SPECIFIC_TOPICS) - covered_topics
    uncovered_core = topics.intersection(CORE_TOPICS) - covered_topics
    source_bonus = 1 if candidate["source"] not in used_sources else 0
    return (
        float(len(uncovered_specific)),
        float(len(uncovered_core)),
        float(source_bonus),
        float(choice.get("score") or 0),
    )


def _best_coverage_choice(choices: list[tuple[dict, dict]], covered_topics: set[str], used_ids: set[int], used_sources: set[str]) -> tuple[dict, dict] | None:
    eligible = [pair for pair in choices if pair[1]["id"] not in used_ids]
    if not eligible:
        return None
    return max(eligible, key=lambda pair: _score_coverage(pair[1], pair[0], covered_topics, used_sources))


def _best_ranked_fill(choices: list[tuple[dict, dict]], covered_topics: set[str], used_ids: set[int], used_sources: set[str]) -> tuple[dict, dict] | None:
    eligible = []
    for choice, candidate in choices:
        if candidate["id"] in used_ids:
            continue
        source_bonus = candidate["source"] not in used_sources
        topics = _topic_set(candidate)
        new_topics = topics - covered_topics
        eligible.append((choice, candidate, source_bonus, new_topics))
    if not eligible:
        return None
    return max(eligible, key=lambda row: (row[2], len(row[3]), float(row[0].get("score") or 0)))[:2]


def select_top5(news=None) -> List[Dict]:
    candidates = build_candidates(items=news)
    selected = rank_with_deepseek(candidates, limit=len(candidates))
    by_id = {item["id"]: item for item in candidates}

    valid_choices: list[tuple[dict, dict]] = []
    for choice in selected:
        try:
            candidate_id = int(choice["id"])
        except (KeyError, TypeError, ValueError):
            continue
        candidate = by_id.get(candidate_id)
        if candidate:
            valid_choices.append((choice, candidate))

    result: list[dict] = []
    used_sources: set[str] = set()
    covered_topics: set[str] = set()
    chosen_ids: set[int] = set()

    target_topics = set(SPECIFIC_TOPICS)
    while len(result) < 5 and not target_topics.issubset(covered_topics):
        picked = _best_coverage_choice(valid_choices, covered_topics, chosen_ids, used_sources)
        if not picked:
            break
        choice, candidate = picked
        new_specific = _topic_set(candidate).intersection(SPECIFIC_TOPICS) - covered_topics
        if not new_specific:
            break
        result.append(_pick_result(candidate, choice))
        chosen_ids.add(candidate["id"])
        used_sources.add(candidate["source"])
        covered_topics.update(_topic_set(candidate))

    if len(result) < 5:
        robotics_choices = [
            pair for pair in valid_choices
            if pair[1]["id"] not in chosen_ids and "robotics" in _topic_set(pair[1])
        ]
        if robotics_choices:
            choice, candidate = max(
                robotics_choices,
                key=lambda pair: (pair[1]["source"] not in used_sources, float(pair[0].get("score") or 0)),
            )
            result.append(_pick_result(candidate, choice))
            chosen_ids.add(candidate["id"])
            used_sources.add(candidate["source"])
            covered_topics.update(_topic_set(candidate))

    while len(result) < 5:
        picked = _best_ranked_fill(valid_choices, covered_topics, chosen_ids, used_sources)
        if not picked:
            break
        choice, candidate = picked
        result.append(_pick_result(candidate, choice))
        chosen_ids.add(candidate["id"])
        used_sources.add(candidate["source"])
        covered_topics.update(_topic_set(candidate))

    if len(result) < 5:
        for candidate in candidates:
            if candidate["id"] in chosen_ids:
                continue
            result.append(_pick_result(candidate, reason="Deterministic fallback from ranked candidates"))
            chosen_ids.add(candidate["id"])
            if len(result) >= 5:
                break

    if len(result) < 5:
        raise RuntimeError(f"Only {len(result)} usable stories available; expected 5")

    for index, item in enumerate(result[:5], start=1):
        item["rank"] = index
    return result[:5]


def main() -> None:
    selected = select_top5()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(selected)} stories")


if __name__ == "__main__":
    main()
