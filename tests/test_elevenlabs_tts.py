import base64
import io
import json
import math
import wave
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest

from app.elevenlabs_tts import ElevenLabsTTSProvider
from app.tts import TTSError, wav_duration
from app.tts_factory import create_tts_provider


def payload(text="Привет, мир!"):
    duration = len(text) * .02 + .2
    return {"audio_base64": base64.b64encode(b"\0\0" * round(duration * 24000)).decode(), "alignment": {
        "characters": list(text), "character_start_times_seconds": [i * .02 for i in range(len(text))],
        "character_end_times_seconds": [(i + 1) * .02 for i in range(len(text))],
    }}


def response(data=None, status=200):
    return httpx.Response(status, content=json.dumps(payload() if data is None else data).encode(),
                          headers={"Content-Type": "application/json"})


def test_factory_selects_elevenlabs_and_rejects_unknown(tts_settings):
    assert isinstance(create_tts_provider(tts_settings), ElevenLabsTTSProvider)
    with pytest.raises(ValueError, match="Unsupported"):
        create_tts_provider(replace(tts_settings, tts_provider="unknown"))


@pytest.mark.parametrize("field,value", [("elevenlabs_api_key", ""), ("elevenlabs_voice_id", ""),
    ("elevenlabs_voice_id", "../secret"), ("elevenlabs_voice_id", "voice?key=oops")])
def test_missing_credentials_or_invalid_voice_rejected_before_network(tts_settings, field, value):
    with pytest.raises(TTSError):
        create_tts_provider(replace(tts_settings, **{field: value}))


def test_request_and_native_word_alignment(monkeypatch, tts_settings):
    post = Mock(return_value=response())
    monkeypatch.setattr(httpx, "post", post)
    speech = create_tts_provider(tts_settings).synthesize("Привет, мир!")
    args, kwargs = post.call_args
    assert args[0] == "https://api.elevenlabs.io/v1/text-to-speech/fixture-voice/with-timestamps"
    assert kwargs["headers"]["xi-api-key"] == "eleven-test-key"
    assert kwargs["params"] == {"output_format": "pcm_24000"}
    assert kwargs["json"] == {"text": "Привет, мир!", "model_id": "fixture-model"}
    assert kwargs["timeout"] == 5
    assert speech.provider == "elevenlabs" and speech.timing_note == "alignment"
    assert [item.word for item in speech.word_timings] == ["Привет,", "мир!"]
    assert speech.word_timings[0].start == 0
    assert speech.word_timings[0].end == pytest.approx(.14)
    assert speech.word_timings[1].start == pytest.approx(.16)
    assert wav_duration(speech.audio_wav) == pytest.approx(.44)
    with wave.open(io.BytesIO(speech.audio_wav), "rb") as file:
        assert (file.getframerate(), file.getnchannels(), file.getsampwidth()) == (24000, 1, 2)


@pytest.mark.parametrize("source,aligned", [("Раз\n\nдва", "Раз два"), ("Ёж", "Е\u0308ж")])
def test_alignment_matches_whitespace_and_unicode_normalization(monkeypatch, tts_settings, source, aligned):
    monkeypatch.setattr(httpx, "post", Mock(return_value=response(payload(aligned))))
    speech = create_tts_provider(tts_settings).synthesize(source)
    assert speech.word_timings is not None


def test_normalized_alignment_used_when_original_is_missing(monkeypatch, tts_settings):
    data = payload()
    data["normalized_alignment"] = data.pop("alignment")
    monkeypatch.setattr(httpx, "post", Mock(return_value=response(data)))
    speech = create_tts_provider(tts_settings).synthesize("Привет, мир!")
    assert speech.timing_note == "normalized_alignment"
    assert speech.word_timings


@pytest.mark.parametrize("case", ["missing", "null", "normalized_different_text"])
def test_missing_or_unusable_alignment_explicitly_requests_estimation(monkeypatch, tts_settings, case):
    data = payload("двадцать рублей")
    if case == "missing":
        del data["alignment"]
    elif case == "null":
        data["alignment"] = None
    else:
        data["normalized_alignment"] = data.pop("alignment")
    monkeypatch.setattr(httpx, "post", Mock(return_value=response(data)))
    speech = create_tts_provider(tts_settings).synthesize("20 рублей")
    assert speech.word_timings is None
    assert speech.timing_note == ("alignment_text_mismatch" if case == "normalized_different_text" else "no_alignment")


@pytest.mark.parametrize("case", ["base64", "empty_audio", "odd_pcm", "compressed_audio", "non_object",
    "array_lengths", "missing_array", "bad_char", "negative_time", "nan_time", "bool_time",
    "decreasing_time", "audio_overrun", "zero_word_duration"])
def test_corrupt_successful_response_is_rejected_without_paid_retry(monkeypatch, tts_settings, case, caplog):
    data = payload()
    if case == "base64": data["audio_base64"] = "not-base64:eleven-test-key"
    elif case == "empty_audio": data["audio_base64"] = ""
    elif case == "odd_pcm": data["audio_base64"] = base64.b64encode(b"x").decode()
    elif case == "compressed_audio": data["audio_base64"] = base64.b64encode(b"RIFFnot raw PCM").decode()
    elif case == "non_object": data = []
    elif case == "array_lengths": data["alignment"]["characters"].pop()
    elif case == "missing_array": del data["alignment"]["characters"]
    elif case == "bad_char": data["alignment"]["characters"][0] = "word"
    elif case == "negative_time": data["alignment"]["character_start_times_seconds"][0] = -1
    elif case == "nan_time": data["alignment"]["character_start_times_seconds"][0] = math.nan
    elif case == "bool_time": data["alignment"]["character_start_times_seconds"][0] = True
    elif case == "decreasing_time": data["alignment"]["character_start_times_seconds"][3] = 0
    elif case == "audio_overrun": data["alignment"]["character_end_times_seconds"][-1] = 99
    else:
        for key in ("character_start_times_seconds", "character_end_times_seconds"):
            data["alignment"][key] = [0] * len(data["alignment"][key])
    post = Mock(return_value=response(data))
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(TTSError, match="invalid audio") as error:
        create_tts_provider(tts_settings).synthesize("Привет, мир!")
    post.assert_called_once()
    assert "eleven-test-key" not in str(error.value) + caplog.text


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504])
def test_transient_errors_retry_then_succeed(monkeypatch, tts_settings, status):
    post = Mock(side_effect=[httpx.Response(status, text="eleven-test-key"), response()])
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.elevenlabs_tts.time.sleep", Mock())
    assert create_tts_provider(tts_settings).synthesize("Привет, мир!").word_timings
    assert post.call_count == 2


@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 422])
def test_permanent_errors_do_not_retry_or_leak_body(monkeypatch, tts_settings, status, caplog):
    post = Mock(return_value=httpx.Response(status, text="eleven-test-key"))
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(TTSError, match=f"HTTP {status}") as error:
        create_tts_provider(tts_settings).synthesize("Привет, мир!")
    post.assert_called_once()
    assert "eleven-test-key" not in str(error.value) + caplog.text


def test_bounded_transport_retries_and_secret_redaction(monkeypatch, tts_settings, caplog):
    post = Mock(side_effect=httpx.ReadTimeout("eleven-test-key"))
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.elevenlabs_tts.time.sleep", Mock())
    with pytest.raises(TTSError, match="after 3 attempts") as error:
        create_tts_provider(tts_settings).synthesize("Привет, мир!")
    assert post.call_count == 3
    assert "eleven-test-key" not in repr(tts_settings) + str(error.value) + caplog.text


def test_retry_after_is_bounded(monkeypatch, tts_settings):
    settings = replace(tts_settings, tts_retry_base_seconds=2, tts_retry_max_seconds=5)
    post = Mock(side_effect=[httpx.Response(429, headers={"Retry-After": "999"}), response()])
    sleep = Mock()
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.elevenlabs_tts.time.sleep", sleep)
    create_tts_provider(settings).synthesize("Привет, мир!")
    sleep.assert_called_once_with(5)


def test_successful_response_with_non_json_body_is_not_retried(monkeypatch, tts_settings, caplog):
    post = Mock(return_value=httpx.Response(200, text="eleven-test-key"))
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(TTSError) as error:
        create_tts_provider(tts_settings).synthesize("Привет")
    post.assert_called_once()
    assert "eleven-test-key" not in str(error.value) + caplog.text


def test_real_adapter_missing_alignment_flows_through_generic_fallback(monkeypatch, tts_settings):
    from app.tts_pipeline import synthesize_audio
    data = payload()
    del data["alignment"]
    post = Mock(return_value=response(data))
    monkeypatch.setattr(httpx, "post", post)
    result = synthesize_audio("Привет, мир!", tts_settings)
    saved = json.loads(result.timings_path.read_text())
    assert result.timing_source == "estimated"
    assert saved["timing_note"] == "no_alignment"
    assert saved["provider"] == "elevenlabs"
    post.assert_called_once()
