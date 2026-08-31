import json

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


def test_ranking_prompt_is_scoped_to_four_editorial_topics():
    prompt = build_ranking_prompt(
        [{"id": 1, "title": "Humanoid", "source": "S", "summary": "x", "topics": ["humanoid"]}],
        limit=5,
    )
    for topic in ("робототехника", "роботы-собаки", "гуманоидные роботы", "экзоскелеты"):
        assert topic in prompt
    assert json.dumps([{"id": 1}], ensure_ascii=False) in prompt or '"id": 1' in prompt
