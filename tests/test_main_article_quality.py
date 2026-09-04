import pytest

from main import _validate_article_quality


def _top5() -> list[dict]:
    return [
        {
            "title": f"Robot event {index}",
            "summary": "The source card reports a robotics event.",
            "url": f"https://example.com/news-{index}",
        }
        for index in range(1, 6)
    ]


def _article() -> dict:
    return {
        "title": "Робототехника дня",
        "intro": (
            "В выпуске собраны новости о робототехнике. "
            "Каждый блок опирается на отдельный источник."
        ),
        "items": [
            {
                "headline": f"Робот {index}: конкретное событие",
                "body": (
                    "Источник сообщает о событии. "
                    "В карточке приведены доступные сведения. "
                    "Текст не добавляет неподтверждённых деталей."
                ),
            }
            for index in range(1, 6)
        ],
    }


def test_final_quality_gate_rechecks_digest_level_facts():
    article = _article()
    article["title"] = "10 роботов дня"

    with pytest.raises(ValueError, match="Article title/intro.*numbers absent"):
        _validate_article_quality(article, _top5())
