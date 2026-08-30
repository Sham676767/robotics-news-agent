from app.ai_client import build_ranking_prompt


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
    assert "валидным JSON" in prompt
