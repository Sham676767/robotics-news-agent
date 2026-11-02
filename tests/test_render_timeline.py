from dataclasses import replace
from pathlib import Path

import pytest

from app.caption_phrases import dangling
from app.config import Settings
from app.render_inputs import RenderAudio
from app.render_subtitles import build_subtitles, render_overlay
from app.render_template import RenderTemplate
from app.render_timeline import Overlay, SAFE, norm_overlays, overlays_for, shots_for, validate_overlays
from app.stub_pipeline import stub_script
from app.tts import WordTiming, estimate_word_timings
from app.typography import layout, measured_font


@pytest.fixture
def timeline():
    _, script, _ = stub_script(Settings())
    audio = RenderAudio(Path("unused.wav"), "unused", 39, estimate_word_timings(script.voiceover, 39), "estimated")
    return script, audio, overlays_for(script, audio, header="БИЗНЕС · ПРАВО РФ", expert="Имя юриста", cta=Settings().client_cta)


def test_every_shot_under_four_seconds_and_alternating_motion():
    shots = shots_for(45, 4)
    assert shots[0].start == 0 and shots[-1].end == 45
    assert all(0 < shot.end - shot.start <= 3.5 + 1 / 30 for shot in shots)
    assert all(left.end == right.start and left.motion != right.motion and left.asset != right.asset for left, right in zip(shots, shots[1:]))


def test_safe_zones_cta_last_eight_seconds_no_urls_or_early_disclaimer(timeline):
    script, audio, overlays = timeline
    validate_overlays(overlays, 39)
    for item in overlays:
        assert SAFE[0] <= item.bounds[0] < item.bounds[2] <= SAFE[2]
        assert 250 <= item.bounds[1] < item.bounds[3] <= 1520
        assert "http" not in item.text
    cta = next(item for item in overlays if item.kind == "cta")
    assert 31 <= cta.start < cta.end == 39
    assert "РАЗБОР" in cta.text
    disclaimer = next(item for item in overlays if item.kind == "disclaimer")
    assert disclaimer.start >= 37 and disclaimer.end == 39
    assert any(item.kind == "number" for item in overlays)
    for item in overlays:
        if item.kind == "caption":
            assert 2 <= len(item.text.split()) <= 5 and not dangling(item.text)
    assert all(item.start >= 0 for item in norm_overlays(script, audio))


def test_norm_is_only_displayed_at_its_actual_spoken_reference(timeline):
    script, audio, _ = timeline
    cards = norm_overlays(script, audio)
    assert len(cards) == 1
    start = next(word.start for word in audio.words if word.word == "статья")
    assert cards[0].start == start
    assert cards[0].end - start <= 3
    assert "999" in cards[0].text and "http" not in cards[0].text
    no_ref = replace(audio, words=(WordTiming("Проверьте", 0, 1), WordTiming("договор", 1, 2)))
    assert norm_overlays(script, no_ref) == ()


def test_actual_font_measurement_prevents_caption_clipping(timeline):
    _, _, overlays = timeline
    for item in overlays:
        if item.kind == "caption":
            size, lines = layout(item.text, "DejaVu Sans", 72, 60, 800, 490, max_lines=2)
            font = measured_font("DejaVu Sans", size)
            assert size >= 60 and len(lines) <= 2
            assert all(font.getlength(line) * 1.08 <= 756 for line in lines)
            assert all(not dangling(line) for line in lines)
            assert r"\clip(100,650,900,1140)" in render_overlay(item, RenderTemplate())


def test_unsafe_and_unreadable_overlay_rejected():
    with pytest.raises(ValueError, match="safe"):
        validate_overlays((Overlay("hook", 0, 2, "Хук", (0, 0, 1000, 1800)),), 39)
    with pytest.raises(ValueError, match="minimum"):
        layout("Ш" * 100, "DejaVu Sans", 72, 60, 800, 400)
