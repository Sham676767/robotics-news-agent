import copy
from dataclasses import replace

import pytest

from app.config import Settings
from app.editorial import FORMATS, publication_caption
from app.reel_script import parse_script
from app.script_review import local_safety_issues, review_claims


def test_editorial_round_trip_caption_and_all_ab_hooks_are_reviewed(editorial_data, script_topic):
    script = parse_script(editorial_data, script_topic, Settings())
    assert script.to_dict() == editorial_data
    assert script.editorial.format == "checklist"
    assert any(c.text == editorial_data["editorial"]["hook_variants"][1] for c in review_claims(script, Settings()))
    caption = publication_caption(script)
    assert caption.splitlines()[0] == script.hook
    assert caption.count(Settings().client_cta) == 1
    assert all(source.url in caption for source in script.sources)
    assert script.disclaimer in caption


@pytest.mark.parametrize("format", FORMATS)
def test_four_formats_accepted(format, editorial_data, script_topic):
    editorial_data["editorial"]["format"] = format
    assert parse_script(editorial_data, script_topic, Settings()).editorial.format == format


@pytest.mark.parametrize("mutation", ["format", "selected", "bool", "duplicate", "too_few", "intro", "invented", "caption", "tags", "points"])
def test_bad_editorial_contract_rejected(mutation, editorial_data, script_topic):
    data = copy.deepcopy(editorial_data)
    editorial = data["editorial"]
    if mutation == "format": editorial["format"] = "unknown"
    elif mutation == "selected": editorial["selected_hook"] = 1
    elif mutation == "bool": editorial["selected_hook"] = False
    elif mutation == "duplicate": editorial["hook_variants"][1] = data["hook"]
    elif mutation == "too_few": editorial["hook_variants"] = [data["hook"]]
    elif mutation == "intro": editorial["hook_variants"][1] = "Сегодня поговорим о договоре"
    elif mutation == "invented": editorial["hook_variants"][1] = "Вам вернут 77778 рублей?"
    elif mutation == "caption": data["caption"] = "Просто подпись"
    elif mutation == "tags": data["hashtags"] = ["#тест"]
    else: data["voiceover"] = data["voiceover"].replace("Этот учебный пример", "И этот учебный пример").replace("разногласий. ", "разногласий; и ")
    with pytest.raises(ValueError):
        parse_script(data, script_topic, Settings())


@pytest.mark.parametrize("template", ["Гарантируем выигрыш. {keyword}", "Если вы напишете {keyword}, обязательно выиграем. Сохраните.",
    "Напишите {missing}", "Напишите без ключевого слова. Сохраните.", "{keyword}", "{keyword}\nСохраните"])
def test_cta_config_cannot_promise_or_omit_required_elements(template):
    with pytest.raises(ValueError):
        Settings(cta_text=template)


def test_config_values_and_legacy_compatibility(script_data, script_topic):
    settings = Settings.from_env({"CTA_KEYWORD": "ДОГОВОР", "CTA_CONTACT": "в комментариях", "EXPERT_NAME": "Юрист", "COVER_FRAME_SECONDS": "2"})
    assert "«ДОГОВОР» в комментариях" in settings.client_cta
    assert settings.cover_frame_seconds == 2
    assert parse_script(script_data, script_topic, settings).editorial is None


def test_unchosen_hook_also_subject_to_safety(editorial_data, script_topic):
    script = parse_script(editorial_data, script_topic, Settings())
    bad = replace(script, editorial=replace(script.editorial, hook_variants=(script.hook, "Вам точно положено возмещение")))
    assert any(issue.code == "categorical_claim" and issue.field == "hook_variants[1]" for issue in local_safety_issues(bad, script_topic))


def test_contact_can_contain_user_supplied_phone_numbers(editorial_data, script_topic):
    settings = Settings(cta_contact="по +79991234567")
    old = Settings().client_cta
    editorial_data["voiceover"] = editorial_data["voiceover"].replace(old, settings.client_cta)
    editorial_data["caption"] = editorial_data["caption"].replace(old, settings.client_cta)
    script = parse_script(editorial_data, script_topic, settings)
    assert not local_safety_issues(script, script_topic, settings)


def test_music_attribution_is_in_caption(editorial_data, script_topic):
    script = parse_script(editorial_data, script_topic, Settings())
    assert "Музыка: Автор — CC-BY-4.0" in publication_caption(script, music_credit="Автор — CC-BY-4.0")


@pytest.mark.parametrize("value", [True, -1, 3])
def test_invalid_hook_variant(value):
    with pytest.raises(ValueError, match="HOOK_VARIANT"):
        Settings(hook_variant=value)


@pytest.mark.parametrize("value", [True, 0, 3, float("nan")])
def test_cover_offset_must_stay_on_opening_hook(value):
    with pytest.raises(ValueError, match="COVER_FRAME_SECONDS"):
        Settings(cover_frame_seconds=value)
