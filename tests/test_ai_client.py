import json
from datetime import datetime, timedelta, timezone

from app.ai_client import _extract_json, _heuristic_fallback, build_ranking_prompt


def test_ranking_prompt_is_compact_and_structured():
    prompt = build_ranking_prompt(
        [
            {
                "id": 1,
                "title": "Humanoid robot demo",
                "source": "Test source",
                "published_at": "2026-08-30T08:00:00+00:00",
                "summary": "A short robotics summary.",
                "topics": ["humanoid"],
            }
        ]
    )

    assert "Humanoid robot demo" in prompt
    assert '"id": 1' in prompt
    assert "JSON" in prompt
    assert "robotaxi" in prompt


def test_extract_json_accepts_markdown_fence():
    assert _extract_json('```json\n[{"id": 1}]\n```') == [{"id": 1}]


def test_extract_json_recovers_embedded_array():
    assert _extract_json('answer: [{"id": 2, "score": 9}] done') == [{"id": 2, "score": 9}]


def test_heuristic_fallback_prioritizes_specific_editorial_topics():
    items = [
        {"id": 1, "title": "General robotics", "topics": ["robotics"], "summary": "long"},
        {"id": 2, "title": "Humanoid robot", "topics": ["humanoid"], "summary": "short"},
        {"id": 3, "title": "Robot dog", "topics": ["robot_dog"], "summary": "short"},
    ]
    result = _heuristic_fallback(items, limit=2)
    assert [item["id"] for item in result] == [2, 3]


def test_heuristic_fallback_prefers_fresh_concrete_story_over_old_specific_and_aggregated_items():
    now = datetime.now(timezone.utc)
    items = [
        {"id": 1, "title": "Old humanoid commentary", "source": "New Atlas Robotics", "topics": ["humanoid"], "published_at": (now - timedelta(days=7)).isoformat(), "summary": "A long but old general discussion of humanoid robots."},
        {"id": 2, "title": "Robot dog demonstrated in warehouse pilot", "source": "Direct Publisher", "topics": ["robot_dog"], "published_at": (now - timedelta(hours=18)).isoformat(), "summary": "The company demonstrated a quadruped robot in a concrete warehouse deployment pilot with operators."},
        {"id": 3, "title": "Humanoid roundup - Interesting Engineering", "source": "Google News Robotics Research", "topics": ["humanoid"], "published_at": (now - timedelta(hours=12)).isoformat(), "summary": "An aggregated headline that points to another publisher."},
        {"id": 4, "title": "Company discusses physical AI market hurdles", "source": "The Robot Report", "topics": ["robotics"], "published_at": (now - timedelta(hours=6)).isoformat(), "summary": "A company discusses market outlook and industry trends."},
    ]

    result = _heuristic_fallback(items, limit=4)

    assert result[0]["id"] == 2
    assert result.index(next(item for item in result if item["id"] == 3)) > 0
    assert result.index(next(item for item in result if item["id"] == 4)) > 0


def test_ranking_prompt_is_scoped_to_four_editorial_topics():
    prompt = build_ranking_prompt(
        [{"id": 1, "title": "Humanoid", "source": "S", "summary": "x", "topics": ["humanoid"]}],
        limit=5,
    )
    for topic in ("робототехника", "роботы-собаки", "гуманоидные роботы", "экзоскелеты"):
        assert topic in prompt
    assert json.dumps([{"id": 1}], ensure_ascii=False) in prompt or '"id": 1' in prompt
