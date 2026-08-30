from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ai_client import rank_with_deepseek
from .collector import collect_all
from .ranking import rank
from .relevance import filter_relevant

OUTPUT_PATH = Path("data/latest_top5.json")

# A daily news product must not quietly publish stale stories.
MAX_AGE = timedelta(days=14)
MAX_PER_SOURCE = 2


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


def build_candidates(limit: int = 12) -> list[dict]:
    items = filter_relevant(collect_all())
    recent = _recent(items)
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
            "topics": item.topics,
        }
        for index, item in enumerate(ranked, start=1)
    ]


def select_top5(news): -> list[dict]:
    candidates = build_candidates()
    selected = rank_with_deepseek(candidates)
    by_id = {item["id"]: item for item in candidates}

    result: list[dict] = []
    used_sources: set[str] = set()

    # First take the AI choices, validating IDs and source diversity.
    for choice in selected:
        try:
            candidate_id = int(choice["id"])
        except (KeyError, TypeError, ValueError):
            continue
        candidate = by_id.get(candidate_id)
        if not candidate:
            continue
        source = candidate["source"]
        if source in used_sources and len(used_sources) < 3:
            continue
        used_sources.add(source)
        result.append(
            {
                "rank": len(result) + 1,
                "id": candidate_id,
                "title": candidate["title"],
                "source": source,
                "url": candidate["url"],
                "published_at": candidate["published_at"],
                "summary": candidate["summary"],
                "topics": candidate["topics"],
                "ai_score": choice.get("score"),
                "why_selected": choice.get("reason", ""),
            }
        )
        if len(result) >= 5:
            break

    # A free model may return fewer than five usable choices. Fill the gaps
    # deterministically from the already ranked candidate pool instead of
    # failing the whole daily run.
    if len(result) < 5:
        chosen_ids = {item["id"] for item in result}
        for candidate in candidates:
            if candidate["id"] in chosen_ids:
                continue
            source = candidate["source"]
            # Prefer new sources while there are at least three distinct ones.
            if source in used_sources and len(used_sources) < 3:
                continue
            used_sources.add(source)
            result.append(
                {
                    "rank": len(result) + 1,
                    "id": candidate["id"],
                    "title": candidate["title"],
                    "source": source,
                    "url": candidate["url"],
                    "published_at": candidate["published_at"],
                    "summary": candidate["summary"],
                    "topics": candidate["topics"],
                    "ai_score": None,
                    "why_selected": "Filled by deterministic fallback because AI returned fewer than 5 usable choices",
                }
            )
            if len(result) >= 5:
                break

    # Last resort: candidates are already relevance-ranked and source-capped,
    # so this remains deterministic and safe if the source pool is small.
    if len(result) < 5:
        chosen_ids = {item["id"] for item in result}
        for candidate in candidates:
            if candidate["id"] in chosen_ids:
                continue
            result.append(
                {
                    "rank": len(result) + 1,
                    "id": candidate["id"],
                    "title": candidate["title"],
                    "source": candidate["source"],
                    "url": candidate["url"],
                    "published_at": candidate["published_at"],
                    "summary": candidate["summary"],
                    "topics": candidate["topics"],
                    "ai_score": None,
                    "why_selected": "Final deterministic fallback from ranked candidates",
                }
            )
            if len(result) >= 5:
                break

    return result[:5]


def main() -> None:
    selected = select_top5()
    if len(selected) < 5:
        raise RuntimeError(
            f"Only {len(selected)} usable stories available; expected 5"
        )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(selected)} stories")
    for item in selected:
        print(f"#{item['rank']} {item['title']} — {item['source']}")


if __name__ == "__main__":
    main()
