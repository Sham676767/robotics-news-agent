from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.caption_phrases import caption_lines, phrase_captions, starts_particle
from app.config import Settings
from app.editorial import SceneCue, parse_editorial
from app.render_inputs import RenderAudio
from app.render_media import background_sequence, mix_video
from app.render_subtitles import build_subtitles, render_overlay
from app.render_template import RenderTemplate
from app.render_timeline import overlays_for, shots_for
from app.scene_visuals import load_visuals, match_shots
from app.stub_pipeline import stub_script
from app.tts import estimate_word_timings
from app.typography import layout
from app.video_renderer import STUB_HEADER, presentation_header


@pytest.mark.parametrize("particle", ["ли", "бы", "же", "то", "не", "ни"])
def test_particles_attach_to_previous_word_on_screen_and_line(particle):
    text = f"Проверьте, заметен {particle} призыв написать нам в конце ролика."
    phrases = phrase_captions(estimate_word_timings(text, 5))
    for phrase in phrases:
        assert not starts_particle(phrase.text)
        assert not phrase.text.endswith((",", ";", ":", "—", "–"))
        assert all(not starts_particle(line) for line in caption_lines(phrase.text))
        _, lines = layout(phrase.text, "DejaVu Sans", 72, 60, 800, 490, max_lines=3)
        assert all(not starts_particle(line) for line in lines)
    containing = next(phrase for phrase in phrases if any(w.word == particle for w in phrase.words))
    assert containing.words[0].word != particle


def test_initial_orphan_particle_fails_without_dropping_spoken_words():
    with pytest.raises(ValueError, match="split"):
        phrase_captions(estimate_word_timings("ли призыв написать нам", 2))


@pytest.mark.parametrize("punctuation", [",", ";", ":", "—", "–"])
def test_caption_boundary_has_no_dangling_punctuation(punctuation):
    words = estimate_word_timings(f"Проверьте договор{punctuation} затем сохраните документы.", 3)
    assert all(not phrase.text.endswith(punctuation) for phrase in phrase_captions(words))


@pytest.fixture
def scene_package():
    _, script, _ = stub_script(Settings())
    audio = RenderAudio(Path("unused.wav"), "unused", 39, estimate_word_timings(script.voiceover, 39), "estimated")
    return script, audio


def test_cta_is_separate_last_five_and_half_seconds_with_large_keyword(scene_package, tmp_path):
    script, audio = scene_package
    theme = RenderTemplate()
    items = overlays_for(script, audio, header="ПРАВО РФ", expert="Эксперт", cta=Settings().client_cta)
    cta = next(item for item in items if item.kind == "cta")
    assert cta.end - cta.start == 5.5
    assert cta.bounds == (100, 520, 900, 1390)
    assert all(item.end <= cta.start for item in items if item.kind not in {"cta", "disclaimer"})
    ass = render_overlay(cta, theme, cta_keyword="РАЗБОР")
    assert r"\fs112" in ass and "РАЗБОР" in ass and r"\bord0" in ass
    calls = []
    mix_video(tmp_path, "ffmpeg", Path("voice.wav"), 39, None, None, lambda args, **kw: calls.append(args), cta_start=cta.start)
    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "drawbox=x=0:y=0:w=iw:h=ih" in graph and "gte(t,33.500000)" in graph
    assert graph.index("drawbox") < graph.index("ass=subtitles")


def test_light_background_has_no_full_frame_dimming(tmp_path):
    calls = []
    background_sequence(tmp_path, "ffmpeg", [Path("photo.png")], shots_for(3, 1), lambda args, **kw: calls.append(args))
    graph = calls[0][calls[0].index("-vf") + 1]
    assert "brightness=0:" in graph and "drawbox" not in graph and "fade=" not in graph
    from PIL import Image, ImageStat
    with Image.open(tmp_path / "fallback.png") as image:
        assert min(ImageStat.Stat(image.crop((0, 1152, 1080, 1920))).mean) > 190


def test_visuals_selected_by_scene_tags_and_unknown_tag_falls_back(tmp_path, scene_package):
    script, audio = scene_package
    for name in ("document.png", "phone.png"):
        (tmp_path / name).write_bytes(b"local")
    (tmp_path / "library.yaml").write_text(yaml.safe_dump([
        {"file": "document.png", "tags": ["document"]}, {"file": "phone.png", "tags": ["phone"]}]))
    assets = load_visuals(tmp_path)
    shots = match_shots(shots_for(39, 2), script, audio, assets)
    assert shots[0].asset == 0 and shots[1].asset == 1
    assert all(assets[shot.asset].tags & set(shot.tags) for shot in shots if shot.asset >= 0)
    unknown = replace(script, editorial=replace(script.editorial, scenes=(SceneCue(script.voiceover, ("court",)),)))
    assert all(shot.asset == -1 for shot in match_shots(shots, unknown, audio, assets))
    assert all(shot.asset == -1 for shot in match_shots(shots, replace(script, editorial=None), audio, assets))


@pytest.mark.parametrize("entry", [
    {"file": "../escape.png", "tags": ["phone"]},
    {"file": "missing.png", "tags": ["phone"]},
    {"file": "photo.png", "tags": ["Invalid"]},
    {"file": "photo.png", "tags": "phone"},
])
def test_invalid_visual_manifest_rejected(tmp_path, entry):
    (tmp_path / "photo.png").write_bytes(b"local")
    (tmp_path / "library.yaml").write_text(yaml.safe_dump([entry]))
    with pytest.raises(ValueError):
        load_visuals(tmp_path)


def test_scene_contract_roundtrip_and_order(scene_package):
    script, _ = scene_package
    assert parse_editorial(script.editorial.to_dict(), script.hook, script.voiceover) == script.editorial
    bad = script.editorial.to_dict()
    bad["scenes"][0]["text"] = "Не произносится"
    with pytest.raises(ValueError, match="voiceover"):
        parse_editorial(bad, script.hook, script.voiceover)
    old = script.editorial.to_dict()
    del old["scenes"]
    assert "scenes" not in parse_editorial(old, script.hook).to_dict()


@pytest.mark.parametrize("stub", [True, False])
def test_fixture_warning_only_in_explicit_stub_mode(scene_package, stub):
    script, audio = scene_package
    # Even an accidentally reused old stub template cannot leak the warning to live output.
    header = presentation_header(STUB_HEADER, stub=stub)
    items = overlays_for(script, audio, header=header, expert="", cta=Settings().client_cta)
    ass = build_subtitles(script, audio, RenderTemplate(), Settings().client_cta, overlays=items, cta_keyword="РАЗБОР")
    assert (STUB_HEADER in ass) is stub


def test_spoken_article_number_in_words_triggers_only_matching_norm(scene_package):
    from app.render_timeline import norm_overlays
    from app.tts import WordTiming
    script, audio = scene_package
    script = replace(script, sources=(replace(script.sources[0], article="9"),))
    audio = replace(audio, words=(WordTiming("статья", 4, 4.3), WordTiming("девять", 4.3, 4.7)))
    cards = norm_overlays(script, audio)
    assert len(cards) == 1 and "ст. 9" in cards[0].text and cards[0].start == 4
    assert norm_overlays(replace(script, sources=(replace(script.sources[0], article="8"),)), audio) == ()


@pytest.mark.parametrize("seconds", [4.9, 6.1, float("nan"), "5.5"])
def test_cta_duration_must_be_five_to_six_seconds(seconds):
    with pytest.raises(ValueError, match="cta_seconds"):
        RenderTemplate(cta_seconds=seconds)


@pytest.mark.parametrize("scenes", [[], [{"text": "Хук", "tags": ["Bad"]}], [{"text": "Хук", "tags": "document"}], [None]])
def test_invalid_scene_contract_rejected(scene_package, scenes):
    script, _ = scene_package
    value = script.editorial.to_dict()
    value["scenes"] = scenes
    with pytest.raises(ValueError):
        parse_editorial(value, script.hook, script.voiceover)


def test_invalid_yaml_and_duplicate_asset_rejected(tmp_path):
    manifest = tmp_path / "library.yaml"
    manifest.write_text("[unclosed")
    with pytest.raises(ValueError, match="YAML"):
        load_visuals(tmp_path)
    (tmp_path / "local.jpg").write_bytes(b"local")
    entry = {"file": "local.jpg", "tags": ["document"]}
    manifest.write_text(yaml.safe_dump([entry, entry]))
    with pytest.raises(ValueError, match="Duplicate"):
        load_visuals(tmp_path)


def test_logo_is_hidden_on_cta_screen(tmp_path):
    calls = []
    mix_video(tmp_path, "ffmpeg", Path("voice.wav"), 39, None, Path("logo.png"), lambda args, **kw: calls.append(args), cta_start=33.5)
    graph = calls[0][calls[0].index("-filter_complex")+1]
    assert "overlay=820:370:shortest=1:enable='lt(t,33.500000)'" in graph


def test_scene_requires_text_voiceover(scene_package):
    script, _ = scene_package
    with pytest.raises(ValueError, match="voiceover"):
        parse_editorial(script.editorial.to_dict(), script.hook, 42)


def test_subtitle_builder_honors_custom_end_card_duration(scene_package):
    script, audio = scene_package
    ass = build_subtitles(script, audio, RenderTemplate(cta_seconds=6), Settings().client_cta, cta_keyword="РАЗБОР")
    assert "0:00:33.00,0:00:39.00,CTA" in ass
