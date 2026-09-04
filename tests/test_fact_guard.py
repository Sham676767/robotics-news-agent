import pytest

from app.fact_guard import validate_factual_grounding


def _article(body: str) -> dict:
    return {
        "items": [
            {"headline": "Событие", "body": body, "card_index": 1},
        ],
    }


def _cards() -> list[dict]:
    return [{
        "title": "Robot 42 completes a 1.8 meter test",
        "summary": "Company reported that Robot 42 completed a test.",
    }]


def test_accepts_numbers_present_in_the_matching_source_card():
    validate_factual_grounding(
        _article("Робот 42 завершил испытание длиной 1,8 метра. Источник сообщает об этом."),
        _cards(),
    )


def test_rejects_number_in_digest_intro_absent_from_all_sources():
    article = _article("Робот 42 завершил испытание. Источник сообщает об этом.")
    article["title"] = "10 роботов дня"
    article["intro"] = "В выпуске собраны новости о роботах. Источники описывают отдельные события."
    with pytest.raises(ValueError, match="Article title/intro.*numbers absent"):
        validate_factual_grounding(article, _cards())


def test_rejects_unsupported_embellishment_in_digest_title():
    article = _article("Робот 42 завершил испытание. Источник сообщает об этом.")
    article["title"] = "Новый стандарт в робототехнике"
    article["intro"] = "В выпуске собраны новости о роботах. Источники описывают отдельные события."
    with pytest.raises(ValueError, match="Article title/intro.*unsupported embellishment"):
        validate_factual_grounding(article, _cards())


def test_rejects_numeric_claim_absent_from_source_card():
    with pytest.raises(ValueError, match="numbers absent"):
        validate_factual_grounding(
            _article("Робот 99 завершил испытание. Это подтверждает источник."),
            _cards(),
        )


def test_rejects_recurring_unsupported_embellishment():
    with pytest.raises(ValueError, match="unsupported embellishment"):
        validate_factual_grounding(
            _article("Компания представила робота. Это ключевым шагом для отрасли."),
            _cards(),
        )
