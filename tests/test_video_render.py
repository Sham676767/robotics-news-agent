import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.cli import main
from app.reel_script import parse_script
from app.render_inputs import load_render_audio
from app.render_subtitles import build_subtitles, escape_ass, stamp
from app.render_template import RenderTemplate, load_render_template
from app.script_generator import save_script
from app.script_review import digest, review_script
from app.tts import SynthesizedSpeech, TTSProvider, TTSError
from app.tts_pipeline import synthesize_audio
from app.video_renderer import RenderError, probe_media, render_video, run_media, verify_video


@pytest.fixture
def render_package(monkeypatch, tmp_path, script_topic, script_data, tts_settings, review_payload, wav_bytes):
    theme = tmp_path / "test-theme.yaml"
    theme.write_text("header_text: 'ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ'\n", encoding="utf-8")
    settings = replace(tts_settings, render_output_dir=tmp_path / "renders", render_template=theme)
    script = parse_script(script_data, script_topic, settings)
    monkeypatch.setattr("app.script_review.request_json", Mock(return_value=review_payload(script, script_topic, settings)))
    review = review_script(script, script_topic, settings)
    path = save_script(script, script_topic, settings, tmp_path / "script.json", review=review)
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(24), "mock", "model", "voice")
    audio = synthesize_audio(script.voiceover, settings, provider=provider, script_sha256=digest(script.to_dict()))
    monkeypatch.setattr("app.script_review.request_json", Mock(side_effect=AssertionError("Render must not call LLM")))
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=settings))
    return path, script, audio, settings


def test_editable_brand_and_empty_default(tmp_path):
    default = load_render_template(Path("templates/default.yaml"))
    assert default.service_name == default.contact == ""
    path = tmp_path / "theme.yaml"
    path.write_text("service_name: 'Учебный бренд'\ncontact: 'https://example.org'\n", encoding="utf-8")
    assert load_render_template(path).contact == "https://example.org"


@pytest.mark.parametrize("kwargs", [{"end_seconds": 0}, {"end_seconds": float("nan")},
    {"end_seconds": True}, {"caption_size": 100}, {"caption_size": True}, {"words_per_caption": 0},
    {"background_top": "bad"}, {"text_color": 123456}, {"font": "font,Other"},
    {"service_name": "a\nb"}, {"contact": "a" * 121}])
def test_invalid_theme_rejected(kwargs):
    with pytest.raises(ValueError):
        RenderTemplate(**kwargs)


def test_unknown_theme_key_rejected(tmp_path):
    path = tmp_path / "theme.yaml"
    path.write_text("widht: 1080")
    with pytest.raises(ValueError):
        load_render_template(path)


def test_subtitles_include_all_words_norm_url_disclaimer_and_configurable_end(render_package):
    _, script, audio, _ = render_package
    loaded = load_render_audio(audio.timings_path, script)
    theme = RenderTemplate(service_name="Учебный бренд", contact="example.org")
    ass = build_subtitles(script, loaded, theme, "Сохраните ролик и поделитесь им")
    lines = [line for line in ass.splitlines() if ",Caption," in line and line.startswith("Dialogue:")]
    spoken = " ".join(line.split(",", 9)[9].replace(r"\N", " ") for line in lines)
    assert spoken.split() == script.voiceover.split()
    assert script.sources[0].url in ass
    assert "ст. 999" in ass and "ч. 2" in ass
    assert "Учебный бренд" in ass and "example.org" in ass
    assert "Не является юридической консультацией" in ass
    assert ",0:00:24.00,0:00:27.00,End," in ass
    assert loaded.timing_source == "estimated"


def test_ass_escape_and_centisecond_carry():
    assert escape_ass(r"{\pos(1,2)}") == "｛＼pos(1,2)｝"
    assert stamp(59.999) == "0:01:00.00"


@pytest.mark.parametrize("field,value", [("schema_version", True), ("script_sha256", "bad"),
    ("text", "changed"), ("text_sha256", "bad"), ("audio_sha256", "bad"),
    ("audio_file", "../audio.wav"), ("duration_seconds", float("nan")),
    ("duration_seconds", 25), ("timing_source", "unknown"), ("timing_source", []), ("word_timings", [{}]),
    ("word_timings", [])])
def test_tampered_tts_metadata_rejected(render_package, field, value):
    _, script, audio, _ = render_package
    data = json.loads(audio.timings_path.read_text())
    data[field] = value
    audio.timings_path.write_text(json.dumps(data))
    with pytest.raises((ValueError, TTSError)):
        load_render_audio(audio.timings_path, script)


def test_changed_audio_rejected(render_package):
    _, script, audio, _ = render_package
    audio.audio_path.write_bytes(audio.audio_path.read_bytes() + b"bad")
    with pytest.raises(ValueError, match="checksum"):
        load_render_audio(audio.timings_path, script)


def test_no_review_cannot_render(render_package):
    path, _, audio, settings = render_package
    path.with_suffix(".review.json").unlink()
    assert main(["render", "--input", str(path), "--timings", str(audio.timings_path)]) == 2
    assert not settings.render_output_dir.exists()


def test_missing_tools_report_actionable_error(render_package, monkeypatch):
    path, _, audio, settings = render_package
    monkeypatch.setattr("app.video_renderer.shutil.which", Mock(return_value=None))
    with pytest.raises(RenderError, match="not installed"):
        render_video(path, audio.timings_path, settings)
    assert not settings.render_output_dir.exists()


def test_over_90_seconds_rejected_before_tools(render_package, monkeypatch):
    path, script, audio, settings = render_package
    loaded = load_render_audio(audio.timings_path, script)
    monkeypatch.setattr("app.video_renderer.load_render_audio", Mock(return_value=replace(loaded, duration=88)))
    with pytest.raises(ValueError, match="90 seconds"):
        render_video(path, audio.timings_path, settings)
    assert not settings.render_output_dir.exists()


def test_media_failure_cleans_partial_outputs(render_package, monkeypatch):
    path, _, audio, settings = render_package
    monkeypatch.setattr("app.video_renderer.shutil.which", Mock(return_value="tool"))
    monkeypatch.setattr("app.video_renderer.run_media", Mock(side_effect=RenderError("fixture failure")))
    with pytest.raises(RenderError):
        render_video(path, audio.timings_path, settings)
    assert list(settings.render_output_dir.iterdir()) == []


def test_tool_timeout_is_controlled(monkeypatch):
    import subprocess
    monkeypatch.setattr("app.video_renderer.subprocess.run", Mock(side_effect=subprocess.TimeoutExpired("ffmpeg", 1)))
    with pytest.raises(RenderError, match="timed out"):
        run_media(["ffmpeg"])


@pytest.mark.parametrize("raw", ["[", "[one, two]", "unknown: true"])
def test_malformed_template_fails_cleanly(render_package, tmp_path, raw):
    path, _, audio, settings = render_package
    theme = tmp_path / "invalid.yaml"
    theme.write_text(raw)
    with pytest.raises(ValueError):
        render_video(path, audio.timings_path, settings, template_path=theme)


def test_empty_clips_folder_rejected(render_package, tmp_path, monkeypatch):
    path, _, audio, settings = render_package
    monkeypatch.setattr("app.video_renderer.shutil.which", Mock(return_value="tool"))
    clips = tmp_path / "empty"
    clips.mkdir()
    with pytest.raises(ValueError, match="1–20"):
        render_video(path, audio.timings_path, settings, clips_dir=clips)


def test_native_timing_source_preserved(render_package):
    _, script, audio, _ = render_package
    data = json.loads(audio.timings_path.read_text())
    data["timing_source"] = "provider"
    audio.timings_path.write_text(json.dumps(data))
    assert load_render_audio(audio.timings_path, script).timing_source == "provider"


@pytest.mark.parametrize("name", ["RENDER_OUTPUT_DIR", "RENDER_TEMPLATE", "FFMPEG_BIN", "FFPROBE_BIN"])
def test_empty_render_config_rejected(name):
    from app.config import Settings
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: " "})


@pytest.fixture
def media_tools():
    if not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        pytest.skip("Install FFmpeg/ffprobe or run the integration tests in Docker")


def test_real_gradient_render_cli_and_ffprobe(render_package, media_tools, capsys):
    path, script, audio, settings = render_package
    original = path.read_bytes(), audio.audio_path.read_bytes()
    assert main(["render", "--input", str(path), "--timings", str(audio.timings_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    video = Path(output["video_path"])
    probe = probe_media(video)
    assert verify_video(probe, 27) == pytest.approx(27, abs=0.08)
    metadata = json.loads(Path(output["metadata_path"]).read_text())
    assert metadata["publication_allowed"] is False and metadata["human_review_required"] is True
    assert metadata["script_sha256"] == digest(script.to_dict())
    assert metadata["video_sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert metadata["timing_source"] == "estimated"
    assert (path.read_bytes(), audio.audio_path.read_bytes()) == original
    demo = os.environ.get("RENDER_DEMO_DIR")
    if demo:
        folder = Path(demo)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, folder / "render-demo.mp4")
        shutil.copy2(Path(output["metadata_path"]), folder / "render-demo.json")
        shutil.copy2(video.parent / "subtitles.ass", folder / "render-demo.ass")


def test_real_mixed_local_clips_loop_and_ignore_background_sound(render_package, media_tools, tmp_path):
    path, _, audio, settings = render_package
    clips = tmp_path / "clips with spaces"
    clips.mkdir()
    for index, size in enumerate(("320x240", "240x400")):
        run_media(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={'red' if index else 'blue'}:s={size}:r=12:d=0.5",
                   "-f", "lavfi", "-i", "sine=frequency=600:duration=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-shortest", str(clips / f"clip '{index}.mp4")])
    result = render_video(path, audio.timings_path, settings, clips_dir=clips)
    assert verify_video(probe_media(result.video_path), 27) == pytest.approx(27, abs=0.08)
    assert json.loads(result.metadata_path.read_text())["background"] == "clips"
    # Original narration is silent: the audible sine from clips must not leak into the reel.
    raw = tmp_path / "decoded.pcm"
    run_media(["ffmpeg", "-v", "error", "-i", str(result.video_path), "-map", "0:a:0", "-f", "s16le", str(raw)])
    assert set(raw.read_bytes()) == {0}
    assert sorted(item.name for item in result.video_path.parent.iterdir()) == ["render.json", "subtitles.ass", "video.mp4"]


@pytest.mark.parametrize("mutation", ["size", "codec", "audio", "duration"])
def test_ffprobe_verification_rejects_wrong_output(mutation):
    data = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                         "pix_fmt": "yuv420p", "duration": "27"},
                        {"codec_type": "audio", "codec_name": "aac", "duration": "27"}],
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "27"}}
    if mutation == "size":
        data["streams"][0]["width"] = 1920
    elif mutation == "codec":
        data["streams"][0]["codec_name"] = "mpeg4"
    elif mutation == "audio":
        data["streams"].pop()
    else:
        data["format"]["duration"] = "91"
    with pytest.raises(RenderError):
        verify_video(data, 27)
