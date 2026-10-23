import hashlib
import json
import math
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.tts import (SynthesizedSpeech, TTSProvider, TTSError, WordTiming, estimate_word_timings,
                     validate_word_timings, wav_duration)
from app.tts_pipeline import synthesize_audio


def test_pipeline_uses_only_provider_interface_and_preserves_native_timings(tts_settings, wav_bytes):
    timings = (WordTiming("Раз,", .1, .3), WordTiming("два!", .5, .8))
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(), "mock-provider", "mock-model", "voice", timings)
    result = synthesize_audio("Раз, два!", tts_settings, provider=provider, script_sha256="fixture-script")
    provider.synthesize.assert_called_once_with("Раз, два!")
    assert result.word_timings == timings
    assert result.timing_source == "provider"
    assert result.audio_path.read_bytes() == provider.synthesize.return_value.audio_wav
    meta = json.loads(result.timings_path.read_text())
    assert meta["word_timings"][1] == {"word": "два!", "start": .5, "end": .8}
    assert meta["audio_sha256"] == hashlib.sha256(result.audio_path.read_bytes()).hexdigest()
    assert meta["script_sha256"] == "fixture-script"
    assert meta["duration_seconds"] == 1
    assert meta["publication_allowed"] is False


def test_estimated_fallback_is_marked_and_uses_actual_audio_duration(tts_settings, wav_bytes, caplog):
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(3), "mock", "model", "voice")
    result = synthesize_audio("Коротко. Значительно длиннее!", tts_settings, provider=provider)
    meta = json.loads(result.timings_path.read_text())
    assert result.timing_source == "estimated" and result.duration_seconds == 3
    assert meta["timing_method"] == "phrase_length_v1"
    assert meta["timing_note"] == "provider_did_not_return_word_timings"
    assert "estimated" in caplog.text
    assert meta["word_timings"][1]["start"] > meta["word_timings"][0]["end"]
    validate_word_timings(meta["text"], result.word_timings, 3)


def test_phrase_estimate_preserves_punctuation_and_allocates_by_length():
    text = "Я проверяю.\n\nДокументы — внимательно!"
    timings = estimate_word_timings(text, 10)
    assert [item.word for item in timings] == ["Я", "проверяю.", "Документы", "внимательно!"]
    assert timings[1].end - timings[1].start > timings[0].end - timings[0].start
    assert timings[2].start > timings[1].end
    assert 0 <= timings[0].start < timings[-1].end <= 10


@pytest.mark.parametrize("duration", [0, -1, math.nan, math.inf])
def test_estimate_rejects_invalid_duration(duration):
    with pytest.raises(TTSError):
        estimate_word_timings("Текст", duration)


@pytest.mark.parametrize("text", ["", "  ", "— !!!"])
def test_empty_text_fails_before_provider(tts_settings, text):
    provider = Mock(spec=TTSProvider)
    with pytest.raises(ValueError):
        synthesize_audio(text, tts_settings, provider=provider)
    provider.synthesize.assert_not_called()
    assert not tts_settings.tts_output_dir.exists()


@pytest.mark.parametrize("bad", [
    (), (WordTiming("Иное", 0, .5),), (WordTiming("Текст", -.1, .5),),
    (WordTiming("Текст", 0, 2),), (WordTiming("Текст", .5, .5),),
    (WordTiming("Текст", math.nan, .5),), (WordTiming("Текст", False, .5),),
])
def test_corrupt_native_timings_are_not_silently_replaced(tts_settings, wav_bytes, bad):
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(), "mock", "model", "voice", bad)
    with pytest.raises(TTSError):
        synthesize_audio("Текст", tts_settings, provider=provider)
    assert not tts_settings.tts_output_dir.exists()


def test_overlapping_words_are_rejected():
    with pytest.raises(TTSError, match="overlap"):
        validate_word_timings("Раз два", (WordTiming("Раз", 0, .7), WordTiming("два", .6, .9)), 1)


@pytest.mark.parametrize("audio", [b"", b"not-a-wave", b"RIFFbad"])
def test_invalid_audio_rejected(audio):
    with pytest.raises(TTSError):
        wav_duration(audio)


def test_truncated_audio_is_rejected(wav_bytes):
    with pytest.raises(TTSError, match="truncated"):
        wav_duration(wav_bytes()[:-2])


def test_no_overwriting_and_pair_saved_in_each_new_directory(tts_settings, wav_bytes):
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(), "mock", "model", "voice")
    first = synthesize_audio("Текст", tts_settings, provider=provider)
    second = synthesize_audio("Текст", tts_settings, provider=provider)
    assert first.audio_path.parent != second.audio_path.parent
    for result in (first, second):
        assert sorted(path.name for path in result.audio_path.parent.iterdir()) == ["audio.wav", "timings.json"]
    assert not list(tts_settings.tts_output_dir.glob(".tts-*"))


def test_disk_failure_leaves_no_half_result(monkeypatch, tts_settings, wav_bytes):
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(), "mock", "model", "voice")
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("fixture disk failure")))
    with pytest.raises(OSError):
        synthesize_audio("Текст", tts_settings, provider=provider)
    assert list(tts_settings.tts_output_dir.iterdir()) == []


def test_provider_failure_creates_no_output(tts_settings):
    provider = Mock(spec=TTSProvider)
    provider.synthesize.side_effect = TTSError("fixture unavailable")
    with pytest.raises(TTSError):
        synthesize_audio("Текст", tts_settings, provider=provider)
    assert not tts_settings.tts_output_dir.exists()


@pytest.mark.parametrize("name,value", [
    ("TTS_TIMEOUT", "nan"), ("TTS_TIMEOUT", "0"), ("TTS_MAX_ATTEMPTS", "0"),
    ("TTS_MAX_ATTEMPTS", "bad"), ("TTS_RETRY_BASE_SECONDS", "-1"),
    ("TTS_RETRY_MAX_SECONDS", "1"), ("TTS_OUTPUT_DIR", " "), ("TTS_PROVIDER", ""),
    ("ELEVENLABS_MODEL_ID", ""),
])
def test_invalid_tts_settings(name, value):
    with pytest.raises(ValueError):
        Settings.from_env({name: value})


def test_tts_settings_load_from_environment_without_exposing_key():
    settings = Settings.from_env({"TTS_PROVIDER": "ElevenLabs", "TTS_OUTPUT_DIR": "custom/audio",
        "ELEVENLABS_API_KEY": "fixture-key", "ELEVENLABS_VOICE_ID": "fixture-voice",
        "ELEVENLABS_MODEL_ID": "fixture-model", "TTS_TIMEOUT": "7", "TTS_MAX_ATTEMPTS": "2"})
    assert settings.tts_provider == "elevenlabs"
    assert settings.tts_output_dir == Path("custom/audio")
    assert settings.tts_timeout == 7 and settings.tts_max_attempts == 2
    assert settings.elevenlabs_voice_id == "fixture-voice" and settings.elevenlabs_model_id == "fixture-model"
    assert "fixture-key" not in repr(settings)
