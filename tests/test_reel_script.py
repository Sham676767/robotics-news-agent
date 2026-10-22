"""All source material below is a synthetic fixture, not legal advice."""
import copy
from dataclasses import replace

import pytest

from app.config import Settings
from app.reel_script import SCRIPT_SCHEMA, parse_script, topic_sources, word_count


def test_contract_round_trip_and_word_count(script_data, script_topic):
    result = parse_script(script_data, script_topic, Settings())
    assert result.to_dict() == script_data
    assert 80 <= word_count(result.voiceover) <= 140
    assert set(result.to_dict()) == set(SCRIPT_SCHEMA["required"])
    assert SCRIPT_SCHEMA["additionalProperties"] is False
    assert SCRIPT_SCHEMA["properties"]["sources"]["items"]["additionalProperties"] is False


@pytest.mark.parametrize("field", SCRIPT_SCHEMA["required"])
def test_every_field_required(script_data, script_topic, field):
    del script_data[field]
    with pytest.raises(ValueError, match="exactly"):
        parse_script(script_data, script_topic, Settings())


@pytest.mark.parametrize("field,value", [
    ("hook", 1), ("voiceover", None), ("caption", "  "), ("disclaimer", "Другое"),
    ("on_screen_text", []), ("on_screen_text", [None]), ("on_screen_text", "текст"),
    ("hashtags", []), ("hashtags", ["безРешётки"]), ("hashtags", ["#два слова"]),
    ("hashtags", ["#договор", "#договор"]), ("hashtags", [False]),
    ("sources", []), ("sources", ["https://law.example"]),
])
def test_invalid_schema_values(script_data, script_topic, field, value):
    script_data[field] = value
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())


def test_unknown_top_level_field_rejected(script_data, script_topic):
    script_data["cta"] = "лишнее поле"
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())


@pytest.mark.parametrize("change", ["url", "citation", "title", "extra", "missing", "duplicate", "omit"])
def test_source_cards_cannot_be_fabricated_or_lost(script_data, script_topic, change):
    if change == "extra":
        script_data["sources"][0]["kind"] = "law"
    elif change == "missing":
        del script_data["sources"][0]["citation"]
    elif change == "duplicate":
        script_data["sources"].append(copy.deepcopy(script_data["sources"][0]))
    elif change == "omit":
        script_data["sources"].pop()
    else:
        script_data["sources"][0][change] = "https://other.example" if change == "url" else "Выдумка"
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())


@pytest.mark.parametrize("count,valid", [(79, False), (80, True), (140, True), (141, False)])
def test_full_voiceover_word_boundaries(script_data, script_topic, count, valid):
    rest = count - word_count(script_data["hook"]) - word_count(Settings().script_cta)
    script_data["voiceover"] = "\n\n".join([
        script_data["hook"], " ".join(["проверка"] * (rest - 1)), "документы", Settings().script_cta,
    ])
    assert word_count(script_data["voiceover"]) == count
    if valid:
        parse_script(script_data, script_topic, Settings())
    else:
        with pytest.raises(ValueError, match="80–140"):
            parse_script(script_data, script_topic, Settings())


@pytest.mark.parametrize("change", ["prefix", "cta", "paragraphs", "long_hook", "english", "number", "citation"])
def test_structure_language_and_grounding(script_data, script_topic, change):
    if change == "prefix":
        script_data["hook"] = "Другой короткий хук"
    elif change == "cta":
        script_data["voiceover"] = script_data["voiceover"].replace(Settings().script_cta, "Звоните прямо сейчас")
    elif change == "paragraphs":
        script_data["voiceover"] = script_data["voiceover"].replace("\n\n", " ")
    elif change == "long_hook":
        script_data["hook"] = " ".join(["проверка"] * 9)
    elif change == "english":
        script_data["caption"] = "Review all the documents before signing the agreement."
    elif change == "number":
        script_data["caption"] = "Проверьте договор за 77778 дней."
    else:
        # Same number exists in evidence, but a different legal identifier must fail.
        script_topic = replace(script_topic, articles=(replace(script_topic.articles[0], text="Учебный пример 15-ФЗ."),))
        script_data["caption"] = "Учебный пример: статья 15 ГК РФ."
    with pytest.raises(ValueError):
        parse_script(script_data, script_topic, Settings())


def test_configurable_cta_and_punctuation(script_data, script_topic):
    settings = Settings(script_cta="Сохраните этот разбор")
    script_data["voiceover"] = script_data["voiceover"].replace(Settings().script_cta, settings.script_cta + ".")
    parse_script(script_data, script_topic, settings)


@pytest.mark.parametrize("cta", ["", "  ", "Первая\nВторая", "Первая\rВторая"])
def test_invalid_cta_config(cta):
    with pytest.raises(ValueError, match="SCRIPT_CTA"):
        Settings(script_cta=cta)


def test_cta_from_environment():
    assert Settings.from_env({"SCRIPT_CTA": "Сохраните разбор"}).script_cta == "Сохраните разбор"


def test_unverified_primary_reference_is_rejected(script_topic):
    topic = replace(script_topic, references=(replace(script_topic.references[0], availability_verified=False),))
    with pytest.raises(ValueError, match="unverified"):
        topic_sources(topic)


def test_word_count_hyphens_and_numbers():
    assert word_count("Купля-продажа: 10 слов, онлайн-консультация.") == 4
