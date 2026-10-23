import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.cli import main
from app.reel_script import parse_script
from app.script_generator import save_script
from app.script_review import digest, load_checked_script, review_script
from app.tts import SynthesizedSpeech, TTSProvider, TTSError, estimate_word_timings


@pytest.fixture
def checked_script(monkeypatch, tmp_path, script_topic, script_data, tts_settings, review_payload):
    script = parse_script(script_data, script_topic, tts_settings)
    reply = review_payload(script, script_topic, tts_settings)
    monkeypatch.setattr("app.script_review.request_json", Mock(return_value=reply))
    review = review_script(script, script_topic, tts_settings)
    path = save_script(script, script_topic, tts_settings, tmp_path / "script.json", review=review)
    return path, script


@pytest.fixture
def fake_provider(monkeypatch, checked_script, wav_bytes):
    _, script = checked_script
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(5), "mock", "model", "voice",
                                                        estimate_word_timings(script.voiceover, 5))
    factory = Mock(return_value=provider)
    monkeypatch.setattr("app.tts_pipeline.create_tts_provider", factory)
    return provider, factory


def test_cli_speaks_full_voiceover_once_and_outputs_audio_and_words(monkeypatch, checked_script, fake_provider, tts_settings, capsys):
    path, script = checked_script
    provider, factory = fake_provider
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=tts_settings))
    monkeypatch.setattr("app.script_review.request_json", Mock(side_effect=AssertionError("No extra LLM call during TTS")))
    before = path.read_bytes(), path.with_suffix(".review.json").read_bytes()
    assert main(["tts", "--input", str(path)]) == 0
    provider.synthesize.assert_called_once_with(script.voiceover)
    factory.assert_called_once()
    result = json.loads(capsys.readouterr().out)
    audio, timings = Path(result["audio_path"]), Path(result["timings_path"])
    assert audio.exists() and timings.exists()
    metadata = json.loads(timings.read_text())
    assert metadata["text"] == script.voiceover
    assert metadata["script_sha256"] == digest(script.to_dict())
    assert metadata["timing_source"] == "provider"
    assert (path.read_bytes(), path.with_suffix(".review.json").read_bytes()) == before


def test_output_directory_override(monkeypatch, tmp_path, checked_script, fake_provider, tts_settings, capsys):
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=tts_settings))
    target = tmp_path / "custom-audio"
    assert main(["tts", "--input", str(checked_script[0]), "--output-dir", str(target)]) == 0
    assert Path(json.loads(capsys.readouterr().out)["audio_path"]).parent.parent == target


@pytest.mark.parametrize("failure", ["no_audit", "quarantined", "issues", "missing_claim", "wrong_quote",
    "altered_script", "altered_source", "altered_claim_text", "not_eligible"])
def test_cli_never_speaks_unreviewed_or_changed_script(monkeypatch, checked_script, fake_provider, tts_settings, capsys, failure):
    path, script = checked_script
    audit_path = path.with_suffix(".review.json")
    audit = json.loads(audit_path.read_text())
    if failure == "no_audit":
        audit_path.unlink()
    else:
        if failure == "quarantined": audit["review"]["status"] = "quarantined"
        elif failure == "issues": audit["review"]["issues"] = [{"code": "contradicted"}]
        elif failure == "missing_claim": audit["review"]["claims"].pop()
        elif failure == "wrong_quote": audit["review"]["claims"][0]["quote"] = "Выдуманная цитата, которой нет в источнике."
        elif failure == "altered_script":
            data = script.to_dict()
            data["caption"] = "Изменённая подпись."
            path.write_text(json.dumps(data))
        elif failure == "altered_source": audit["topic"]["primary_references"][0]["content"] += " Изменение."
        elif failure == "altered_claim_text": audit["review"]["claims"][0]["text"] = "Иное утверждение."
        else: audit["review"]["eligible_for_next_stage"] = False
        audit_path.write_text(json.dumps(audit))
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=tts_settings))
    assert main(["tts", "--input", str(path)]) == 2
    assert capsys.readouterr().out == ""
    fake_provider[0].synthesize.assert_not_called()
    fake_provider[1].assert_not_called()
    assert not tts_settings.tts_output_dir.exists()


def test_gate_loads_existing_snapshot_without_network(checked_script, tts_settings):
    path, original = checked_script
    loaded, _, review = load_checked_script(path, tts_settings)
    assert loaded == original and review.passed


def test_provider_failure_leaves_stdout_empty(monkeypatch, checked_script, fake_provider, tts_settings, capsys):
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=tts_settings))
    fake_provider[0].synthesize.side_effect = TTSError("Speech provider unavailable")
    assert main(["tts", "--input", str(checked_script[0])]) == 2
    assert capsys.readouterr().out == ""
    assert not tts_settings.tts_output_dir.exists()


def test_plain_text_cannot_bypass_script_gate(monkeypatch, tmp_path, tts_settings, capsys):
    path = tmp_path / "plain.json"
    path.write_text('{"voiceover":"Произвольный текст"}')
    factory = Mock()
    monkeypatch.setattr("app.tts_pipeline.create_tts_provider", factory)
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=tts_settings))
    assert main(["tts", "--input", str(path)]) == 2
    factory.assert_not_called()
    assert capsys.readouterr().out == ""
