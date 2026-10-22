from dataclasses import replace

import pytest

from app.fact_guard import validate_factual_grounding
from app.models import LegalDraft, LegalSection, LegalSource


def draft(body, *, title="Учебный материал", intro="Проверка исходного текста."):
    return LegalDraft(title, intro, (LegalSection("Описание материала", body, 1),))


def source(content, url="https://example.com/source-99"):
    return LegalSource("Учебный материал", "Тестовый источник", url, content)


@pytest.mark.parametrize(("original", "rewritten"), [
    ("42 и 1.8", "Значения 42 и 1,8."),
    ("5,000 и 13,000", "Значения 5 000 и 13 000."),
    ("1,800.50", "Значение 1 800,5."),
    ("1.800,50", "Значение 1800.5."),
    ("5 000", "Значение 5\u00a0000."),
    ("5 000", "Значение 5\u202f000."),
])
def test_accepts_numbers_from_matching_source(original, rewritten):
    validate_factual_grounding(draft(rewritten), [source(original)])


@pytest.mark.parametrize("text", ["Значение 99.", "Значение 6 000."])
def test_rejects_numbers_absent_from_source(text):
    with pytest.raises(ValueError, match="numbers absent"):
        validate_factual_grounding(draft(text), [source("Значение 5,000.")])


def test_rechecks_title_and_intro_numbers():
    with pytest.raises(ValueError, match="Draft title/intro.*numbers absent"):
        validate_factual_grounding(draft("Текст.", title="10 выводов"), [source("Текст.")])


@pytest.mark.parametrize("scope", ["title", "body"])
def test_rejects_unsupported_embellishment(scope):
    value = draft("Описание.", title="Учебный материал")
    if scope == "title":
        value = replace(value, title="Новый стандарт")
    else:
        value = replace(value, sections=(replace(value.sections[0], body="Это меняет правила игры."),))
    with pytest.raises(ValueError, match="unsupported embellishment"):
        validate_factual_grounding(value, [source("Описание.")])


def test_numbers_from_other_source_do_not_ground_section():
    with pytest.raises(ValueError, match="numbers absent"):
        validate_factual_grounding(draft("Значение 42."), [source("Текст."), source("42")])


def test_url_and_publisher_numbers_are_not_evidence():
    value = replace(source("Текст."), source="Источник 99")
    with pytest.raises(ValueError, match="numbers absent"):
        validate_factual_grounding(draft("Значение 99."), [value])


@pytest.mark.parametrize("index", [0, -1, 2, True])
def test_rejects_invalid_source_binding(index):
    value = draft("Текст.")
    value = replace(value, sections=(replace(value.sections[0], source_index=index),))
    with pytest.raises(ValueError, match="matching source"):
        validate_factual_grounding(value, [source("Текст.")])
