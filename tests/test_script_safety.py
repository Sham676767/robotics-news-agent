"""Synthetic references below deliberately do not describe actual law."""
from dataclasses import asdict, replace

import pytest

from app.config import Settings
from app.fact_guard import categorical_claims, validate_factual_grounding
from app.legal_references import explicit_norms
from app.reel_script import DISCLAIMER, parse_script, topic_sources
from app.script_review import local_safety_issues
from app.topics import topic_from_dict, topic_to_dict


@pytest.mark.parametrize("text", [
    "Вам точно положено возмещение.", "Вам точно не положено возмещение.",
    "Вы гарантированно получите выплату.", "Вы обязательно выиграете дело.",
    "Деньги в любом случае вернут.", "У вас никаких рисков.", "Всем положено возмещение.",
    "Вы точно получите деньги. Не является юридической консультацией",
])
def test_unqualified_categorical_claims_rejected(text):
    assert categorical_claims(text)


@pytest.mark.parametrize("text", [
    "Вам может быть положено возмещение при соблюдении условий.",
    "Если соблюдены условия договора, вам точно положено возмещение.",
    "При условии подтверждения обстоятельств вы обязательно получите ответ.",
    "Нельзя обещать, что вам точно положено возмещение.",
    "Не гарантируем выплату: результат зависит от обстоятельств.",
])
def test_qualified_or_non_categorical_text_allowed(text):
    assert not categorical_claims(text)


def test_qualification_in_another_sentence_does_not_excuse_guarantee():
    assert categorical_claims("Если условия соблюдены, обсудите документы. Вам точно положено возмещение.")


def test_legacy_text_validation_uses_categorical_rule(legal_package):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="categorical"):
        validate_factual_grounding(replace(draft, intro="Вам точно положено возмещение."), sources)


@pytest.mark.parametrize("text,expected", [
    ("ч. 2 ст. 999 99999-ФЗ", ("99999-ФЗ", "999", "2")),
    ("части 2 статьи 999 99999-ФЗ", ("99999-ФЗ", "999", "2")),
    ("статья 999 99999-ФЗ", ("99999-ФЗ", "999", "")),
    ("ч. 2 ст. 999 ГК РФ", ("ГК РФ", "999", "2")),
    ("ст. 999.1 Федерального закона от 01.01.2099 № 99999-ФЗ", ("99999-ФЗ", "999.1", "")),
])
def test_explicit_reference_extraction(text, expected):
    norm = explicit_norms("Синтетическая тестовая строка: " + text)[0]
    assert (norm.law, norm.article, norm.part) == expected


@pytest.mark.parametrize("text", ["статья 999", "99999-ФЗ", "Статья неизвестного закона", "Учебный документ"])
def test_incomplete_reference_is_not_invented(text):
    assert explicit_norms(text) == ()


@pytest.mark.parametrize("field,value,valid", [
    ("on_screen_text", ["я" * 60] * 6, True),
    ("on_screen_text", ["я" * 61], False),
    ("on_screen_text", ["Короткий титр"] * 7, False),
    ("on_screen_text", ["Первая\nВторая"], False),
    ("caption", "я" * 1000, True), ("caption", "я" * 1001, False),
    ("hashtags", ["#" + letter for letter in "абвгдежзик"], True),
    ("hashtags", ["#" + letter for letter in "абвгдежзикл"], False),
    ("hashtags", [], False), ("on_screen_text", [], False),
])
def test_limits_boundaries(script_data, script_topic, field, value, valid):
    script_data[field] = value
    if valid:
        parse_script(script_data, script_topic, Settings())
    else:
        with pytest.raises(ValueError):
            parse_script(script_data, script_topic, Settings())


@pytest.mark.parametrize("text", ["", "Общая информация", "не является юридической консультацией",
    "Информация носит общий характер и не заменяет индивидуальную юридическую консультацию."])
def test_required_disclaimer_exact(script_data, script_topic, text):
    script_data["disclaimer"] = text
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())
    script_data["disclaimer"] = DISCLAIMER
    parse_script(script_data, script_topic, Settings())


@pytest.mark.parametrize("field", ["law", "article", "part"])
def test_norm_fields_are_required_and_immutable(script_data, script_topic, field):
    original = script_data["sources"][0][field]
    del script_data["sources"][0][field]
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())
    script_data["sources"][0][field] = original + "выдумка"
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())


def test_primary_norm_fields_and_media_empty_fields(script_topic):
    primary, media = topic_sources(script_topic)
    assert (primary.law, primary.article, primary.part) == ("99999-ФЗ", "999", "2")
    assert (media.law, media.article, media.part) == ("", "", "")


def test_missing_article_and_primary_content_are_blocking(script_data, script_topic):
    topic = replace(script_topic, references=(replace(script_topic.references[0], content=""),))
    script_data["sources"] = [asdict(source) for source in topic_sources(topic)]
    script = parse_script(script_data, topic, Settings())
    assert {issue.code for issue in local_safety_issues(script, topic)} >= {"missing_norm", "missing_primary_text"}


@pytest.mark.parametrize("text,code", [
    ("Учебная ссылка на статью 999.", None),
    ("Учебная ссылка на статью 998.", "invented_identifier"),
    ("Учебная ссылка на часть 1.", "invented_identifier"),
    ("Учебное дело № А99-999/2099.", "invented_identifier"),
    ("Учебное дело № 2-999/2099.", "invented_identifier"),
    ("Учебная норма: ч. 2 ст. 999 ГК РФ.", "unsupported_norm"),
    ("Вам точно положено возмещение.", "categorical_claim"),
])
def test_local_policy_negative_and_positive_cases(script_data, script_topic, text, code):
    script = parse_script(script_data, script_topic, Settings())
    issues = local_safety_issues(replace(script, caption=text), script_topic)
    codes = {issue.code for issue in issues}
    if code:
        assert code in codes
    else:
        assert not codes


def test_invented_article_not_allowed_even_if_number_exists_as_an_amount(script_data, script_topic):
    script = parse_script(script_data, script_topic, Settings())
    topic = replace(script_topic, articles=(replace(script_topic.articles[0], text="Учебная сумма 998 рублей."),))
    issues = local_safety_issues(replace(script, caption="По статье 998 можно обратиться."), topic)
    assert "invented_identifier" in {issue.code for issue in issues}


def test_part_without_article_parts_is_empty_and_never_guessed(script_data, script_topic):
    content = "Синтетический тест: статья 999 99999-ФЗ. Учебная статья без частей."
    topic = replace(script_topic, references=(replace(script_topic.references[0], content=content),))
    assert topic_sources(topic)[0].part == ""
    assert topic_sources(topic)[0].article == "999"


def test_primary_text_survives_round_trip_and_old_snapshots_remain_readable(script_topic):
    assert topic_from_dict(topic_to_dict(script_topic)) == script_topic
    old = topic_to_dict(script_topic)
    del old["primary_references"][0]["content"]
    assert topic_from_dict(old).references[0].content == ""
