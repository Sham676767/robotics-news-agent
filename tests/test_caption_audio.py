import array
import hashlib
import math
import wave
from pathlib import Path

import pytest

from app.audio_edit import edit_silence, silence_ranges
from app.caption_phrases import caption_lines, dangling, dangling_line, phrase_captions
from app.music import licensed_music
from app.render_inputs import RenderAudio
from app.tts import WordTiming


@pytest.mark.parametrize("text", [
    "Прочитайте условия закона о согласии продавца на скидку.",
    "Проверьте договор и переписку перед обращением к юристу.",
    "Сохраните документы, чтобы не потерять важную информацию.",
    "Что делать, если вы не согласны со списанием денег?",
    "Сумма зависит от договора, а не от обещаний.",
])
def test_semantic_phrases_keep_all_words_and_function_words(text):
    words = tuple(WordTiming(w, i * .2, (i + 1) * .2) for i, w in enumerate(text.split()))
    phrases = phrase_captions(words)
    assert [w for phrase in phrases for w in phrase.words] == list(words)
    for phrase in phrases:
        assert 2 <= len(phrase.words) <= 5
        assert not dangling(phrase.text)
        assert all(not dangling_line(line) for line in caption_lines(phrase.text))
        assert len(caption_lines(phrase.text)) <= 2


def test_impossible_caption_fails_instead_of_losing_a_word():
    with pytest.raises(ValueError):
        phrase_captions((WordTiming("закона", 0, .5), WordTiming("о", .5, 1)))


def make_audio(path: Path, ranges=((.8, 2), (3.2, 5)), duration=6):
    rate = 24000
    samples = array.array("h", (round(3000 * math.sin(2 * math.pi * 220 * i / rate)) if any(a <= i / rate < b for a, b in ranges) else 0 for i in range(round(duration * rate))))
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(samples.tobytes())
    words = (WordTiming("Первое", .8, 2), WordTiming("второе", 3.2, 5))
    return RenderAudio(path, hashlib.sha256(path.read_bytes()).hexdigest(), duration, words, "provider")


def test_silence_edits_remap_words_leave_original_and_limit_pauses(tmp_path):
    audio = make_audio(tmp_path / "source.wav")
    before = audio.path.read_bytes()
    result = edit_silence(audio, tmp_path / "edited.wav")
    assert result.audio.duration == pytest.approx(3.51, abs=.02)
    assert result.audio.words[0].start == pytest.approx(.08, abs=.01)
    assert result.audio.words[1].start - result.audio.words[0].end <= .3
    assert result.tail_silence <= .16
    assert max(b - a for a, b in silence_ranges(result.audio.path)) <= .3
    assert audio.path.read_bytes() == before
    assert result.audio.timing_source == "provider"


def test_all_silent_audio_rejected(tmp_path):
    audio = make_audio(tmp_path / "silent.wav", ())
    with pytest.raises(ValueError, match="entirely silent"):
        edit_silence(audio, tmp_path / "edited.wav")


@pytest.mark.parametrize("mutation", ["commercial", "licence", "traversal", "missing", "attribution"])
def test_unlicensed_or_unsafe_music_rejected(tmp_path, mutation):
    import yaml
    data = {"file": "tone.wav", "license": "original", "commercial_use": True, "source": "Locally composed", "attribution": ""}
    (tmp_path / "tone.wav").write_bytes(b"placeholder")
    if mutation == "commercial": data["commercial_use"] = False
    elif mutation == "licence": data["license"] = "unknown"
    elif mutation == "traversal": data["file"] = "../tone.wav"
    elif mutation == "missing": data["file"] = "missing.wav"
    else: data["license"] = "CC-BY-4.0"
    manifest = tmp_path / "license.yaml"
    manifest.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        licensed_music(manifest)


def test_invalid_music_yaml_is_a_clean_input_error(tmp_path):
    manifest = tmp_path / "license.yaml"
    manifest.write_text("[invalid")
    with pytest.raises(ValueError, match="YAML"):
        licensed_music(manifest)
