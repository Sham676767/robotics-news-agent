import json
import logging
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.cli import main
from app.config import Settings
from app.full_pipeline import run_all
from app.instagram_client import InstagramClient, InstagramError, PublishUncertain
from app.instagram_publisher import publish_draft
from app.pipeline_preflight import dry_run
from app.publishing_config import PublishingSettings
from app.reel_drafts import ReelDrafts, checksum, read_json, write_json
from app.reel_script import parse_script
from app.script_generator import save_script
from app.script_review import digest, review_script
from app.secret_logging import protect_logs
from app.tts import SynthesizedSpeech, TTSProvider
from app.tts_pipeline import synthesize_audio
from app.video_storage import StoredVideo, StorageError, VideoStorage


@pytest.fixture
def publish_settings(tmp_path):
    return Settings(drafts_dir=tmp_path / "drafts", tts_output_dir=tmp_path / "audio", render_output_dir=tmp_path / "videos",
                    openrouter_api_key="sk-or-v1-fixture1234567890", elevenlabs_api_key="fixture-elevenlabs-key", elevenlabs_voice_id="fixture-voice",
                    publishing=PublishingSettings(instagram_user_id="12345", instagram_api_version="v25.0",
                        instagram_access_token="fixture-instagram-secret-token", poll_interval_seconds=0,
                        retry_base_seconds=0, retry_max_seconds=0, s3_endpoint="https://s3.example.org",
                        s3_bucket="test-videos", s3_access_key="fixture-access-key", s3_secret_key="fixture-secret-key"))


@pytest.fixture
def bundle(monkeypatch, tmp_path, publish_settings, script_topic, script_data, review_payload, wav_bytes):
    settings = publish_settings
    script = parse_script(script_data, script_topic, settings)
    monkeypatch.setattr("app.script_review.request_json", Mock(return_value=review_payload(script, script_topic, settings)))
    review = review_script(script, script_topic, settings)
    path = save_script(script, script_topic, settings, tmp_path / "script.json", review=review)
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(1), "mock", "model", "voice")
    audio = synthesize_audio(script.voiceover, settings, provider=provider, script_sha256=digest(script.to_dict()))
    render = tmp_path / "render"
    render.mkdir()
    video = render / "video.mp4"
    video.write_bytes(b"mock-video-only-for-unit-tests")
    (render / "subtitles.ass").write_text("mock captions")
    write_json(render / "render.json", {"template": {"end_seconds": 3}, "script_sha256": digest(script.to_dict()),
                "audio_sha256": checksum(audio.audio_path), "video_sha256": checksum(video),
                "publication_allowed": False, "human_review_required": True})
    probe = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                          "pix_fmt": "yuv420p", "duration": "4"},
                         {"codec_type": "audio", "codec_name": "aac", "duration": "4"}],
             "format": {"format_name": "mov,mp4", "duration": "4"}}
    monkeypatch.setattr("app.reel_drafts.probe_media", Mock(return_value=probe))
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=settings))
    store = ReelDrafts(settings)
    reel_id = store.prepare(path, audio.timings_path, video)
    return store, reel_id, settings


@pytest.fixture
def fake_publication():
    client = Mock(spec=InstagramClient)
    client.create_reel.return_value = "200"
    client.wait_ready.return_value = "FINISHED"
    client.publish.return_value = "300"
    storage = Mock(spec=VideoStorage)
    storage.upload.side_effect = lambda path, key: StoredVideo(key, "https://cdn.example.org/video?signature=fixture-secret")
    return client, storage


def test_package_contains_reviewable_assets_and_approval_is_offline(bundle, monkeypatch):
    store, reel_id, _ = bundle
    assert all((store.path(reel_id) / name).is_file() for name in
               ("script.json", "script.review.json", "sources.json", "caption.txt", "audio.wav", "video.mp4", "timings.json"))
    graph = Mock(side_effect=AssertionError("No API on approve"))
    monkeypatch.setattr("app.instagram_publisher.InstagramClient", graph)
    assert store.approve(reel_id)["status"] == "approved"
    graph.assert_not_called()
    assert read_json(store.path(reel_id) / "state.json")["container_id"] is None


def test_unapproved_draft_never_uploads_or_calls_instagram(bundle, fake_publication):
    _, reel_id, settings = bundle
    client, storage = fake_publication
    with pytest.raises(ValueError, match="Approve"):
        publish_draft(reel_id, settings, client=client, storage=storage)
    assert not client.mock_calls and not storage.mock_calls


@pytest.mark.parametrize("asset", ["script.json", "script.review.json", "audio.wav", "timings.json", "video.mp4", "caption.txt", "sources.json", "render.json"])
def test_changed_asset_invalidates_approval(bundle, fake_publication, asset):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    path = store.path(reel_id) / asset
    path.write_bytes(path.read_bytes() + b" ")
    client, storage = fake_publication
    with pytest.raises(ValueError, match="changed"):
        publish_draft(reel_id, settings, client=client, storage=storage)
    assert not client.mock_calls and not storage.mock_calls


def test_different_account_requires_new_approval(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    changed = replace(settings, publishing=replace(settings.publishing, instagram_user_id="99999"))
    with pytest.raises(ValueError, match="account"):
        publish_draft(reel_id, changed, client=fake_publication[0], storage=fake_publication[1])


def test_publish_order_caption_success_cleanup_and_idempotent_repeat(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    sequence = Mock()
    sequence.attach_mock(client, "api")
    sequence.attach_mock(storage, "storage")
    assert publish_draft(reel_id, settings, client=client, storage=storage)["media_id"] == "300"
    names = [call[0] for call in sequence.mock_calls]
    assert names == ["api.check_quota", "storage.upload", "api.create_reel", "api.wait_ready", "api.check_quota", "api.publish", "storage.delete"]
    caption = client.create_reel.call_args.args[1]
    assert "Не является юридической консультацией" in caption and "#договор" in caption
    state = read_json(store.path(reel_id) / "state.json")
    assert state["status"] == "published" and state["storage"]["deleted"]
    assert "signature=" not in (store.path(reel_id) / "state.json").read_text()
    client.reset_mock(); storage.reset_mock()
    assert publish_draft(reel_id, settings, client=client, storage=storage)["media_id"] == "300"
    assert not client.mock_calls and not storage.mock_calls


def test_no_delete_when_disabled(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    settings = replace(settings, publishing=replace(settings.publishing, s3_delete_after_publish=False))
    client, storage = fake_publication
    publish_draft(reel_id, settings, client=client, storage=storage)
    storage.delete.assert_not_called()


def test_cleanup_failure_does_not_lose_success_or_republish(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    storage.delete.side_effect = StorageError("failed")
    assert publish_draft(reel_id, settings, client=client, storage=storage)["cleanup_pending"]
    client.reset_mock()
    storage.delete.side_effect = None
    assert not publish_draft(reel_id, settings, client=client, storage=storage)["cleanup_pending"]
    assert not client.mock_calls


def test_processing_resume_reuses_saved_container(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    client.wait_ready.side_effect = InstagramError("processing_pending")
    with pytest.raises(InstagramError):
        publish_draft(reel_id, settings, client=client, storage=storage)
    client.wait_ready.side_effect = None
    publish_draft(reel_id, settings, client=client, storage=storage)
    client.create_reel.assert_called_once()
    storage.upload.assert_called_once()
    client.publish.assert_called_once()


@pytest.mark.parametrize("observed", ["PUBLISHED", "FINISHED"])
def test_lost_publish_response_reconciles_without_second_post(bundle, fake_publication, observed):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    client.publish.side_effect = PublishUncertain("publish_response_lost")
    with pytest.raises(PublishUncertain):
        publish_draft(reel_id, settings, client=client, storage=storage)
    assert read_json(store.path(reel_id) / "state.json")["status"] == "publish_unknown"
    client.wait_ready.return_value = observed
    if observed == "PUBLISHED":
        assert publish_draft(reel_id, settings, client=client, storage=storage)["status"] == "published"
    else:
        with pytest.raises(PublishUncertain):
            publish_draft(reel_id, settings, client=client, storage=storage)
    client.publish.assert_called_once()
    storage.upload.assert_called_once()


def test_quota_exhaustion_prevents_upload_and_persists_wait(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    client.check_quota.side_effect = InstagramError("publishing_quota_exhausted", retry_after=60)
    for _ in range(2):
        with pytest.raises(InstagramError):
            publish_draft(reel_id, settings, client=client, storage=storage)
    client.check_quota.assert_called_once()
    assert not storage.mock_calls


def test_presigned_url_too_short_is_not_sent_to_instagram(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    storage.upload.side_effect = lambda path, key: StoredVideo(key, "https://cdn.example.org/video", datetime.now(timezone.utc) + timedelta(seconds=10))
    with pytest.raises(ValueError, match="expires too soon"):
        publish_draft(reel_id, settings, client=client, storage=storage)
    client.create_reel.assert_not_called()


def test_concurrent_publication_is_locked(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    with store.locked():
        with pytest.raises(ValueError, match="Another"):
            publish_draft(reel_id, settings, client=fake_publication[0], storage=fake_publication[1])


def test_publish_dry_run_does_not_change_state_or_use_storage(bundle, fake_publication):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    before = {path.name: path.read_bytes() for path in store.path(reel_id).iterdir()}
    client, storage = fake_publication
    assert publish_draft(reel_id, settings, dry_run=True, client=client, storage=storage)["dry_run"]
    assert before == {path.name: path.read_bytes() for path in store.path(reel_id).iterdir()}
    assert not client.mock_calls and not storage.mock_calls


def fake_local_tools(monkeypatch):
    monkeypatch.setattr("app.pipeline_preflight.shutil.which", Mock(return_value="/fixture/tool"))
    monkeypatch.setattr("app.pipeline_preflight.subprocess.run", Mock(side_effect=lambda args, **kwargs:
                        Mock(returncode=0, stdout=" ass V->V " if "-filters" in args else "DejaVu Sans")))


def test_run_all_dry_run_validates_without_any_network_or_files(monkeypatch, publish_settings, tmp_path, capsys):
    fake_local_tools(monkeypatch)
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=publish_settings))
    storage = Mock(side_effect=AssertionError("No storage"))
    monkeypatch.setattr("app.instagram_publisher.S3VideoStorage", storage)
    before = set(tmp_path.rglob("*"))
    assert main(["run-all", "--dry-run", "--count", "2"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] and result["video_count"] == 2
    assert result["paid_request_estimate"]["tts"] == 2
    assert set(tmp_path.rglob("*")) == before
    storage.assert_not_called()
    assert "fixture-secret-key" not in json.dumps(result)


def test_dry_run_lists_missing_keys_and_tools_without_writes(monkeypatch, tmp_path):
    monkeypatch.setattr("app.pipeline_preflight.shutil.which", Mock(return_value=None))
    settings = Settings(drafts_dir=tmp_path / "drafts", render_output_dir=tmp_path / "renders")
    result = dry_run(settings, Path("sources.yaml"))
    assert not result["ready"]
    text = " ".join(result["issues"])
    assert all(key in text for key in ("OPENROUTER_API_KEY", "ELEVENLABS_API_KEY", "INSTAGRAM_ACCESS_TOKEN", "S3_ACCESS_KEY", "ffmpeg"))
    assert list(tmp_path.iterdir()) == []


def test_stub_dry_run_needs_no_keys(monkeypatch, tmp_path):
    fake_local_tools(monkeypatch)
    result = dry_run(Settings(drafts_dir=tmp_path / "drafts"), Path("sources.yaml"), stub=True)
    assert result["ready"] and result["external_calls"] == [] and result["paid_request_estimate"] == {"total": 0}


def test_dotenv_loaded_without_mutating_environment(monkeypatch, tmp_path):
    import os
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("INSTAGRAM_ACCESS_TOKEN=fixture-dotenv-secret\nINSTAGRAM_USER_ID=12345\n")
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    settings = Settings.from_env()
    assert settings.publishing.instagram_access_token == "fixture-dotenv-secret"
    assert "INSTAGRAM_ACCESS_TOKEN" not in os.environ
    assert "fixture-dotenv-secret" not in repr(settings)


def test_secret_logs_hide_tokens_and_presigned_queries(publish_settings, caplog):
    protect_logs(publish_settings)
    with caplog.at_level(logging.INFO):
        logging.getLogger("app.fixture").info("Token %s URL %s", publish_settings.publishing.instagram_access_token,
                                             "https://cdn.example.org/video?X-Amz-Signature=SECRET")
    assert "fixture-instagram-secret-token" not in caplog.text and "SECRET" not in caplog.text


def test_crash_after_publish_preserves_pending_state_for_reconciliation(bundle, fake_publication, monkeypatch):
    store, reel_id, settings = bundle
    store.approve(reel_id)
    client, storage = fake_publication
    original = write_json
    def fail_success_checkpoint(path, data):
        if data.get("status") == "published":
            raise OSError("simulated disk failure")
        original(path, data)
    monkeypatch.setattr("app.instagram_publisher.write_json", fail_success_checkpoint)
    with pytest.raises(OSError):
        publish_draft(reel_id, settings, client=client, storage=storage)
    assert read_json(store.path(reel_id) / "state.json")["status"] == "publishing"
    storage.delete.assert_not_called()
    monkeypatch.setattr("app.instagram_publisher.write_json", original)
    client.wait_ready.return_value = "PUBLISHED"
    assert publish_draft(reel_id, settings, client=client, storage=storage)["status"] == "published"
    client.publish.assert_called_once()


def test_invalid_dry_run_configuration_returns_problem_list(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(side_effect=ValueError("Invalid publication configuration")))
    assert main(["run-all", "--dry-run"]) == 2
    assert json.loads(capsys.readouterr().out)["issues"] == ["Invalid publication configuration"]


def test_live_run_all_finishes_at_draft_without_approval_or_publication(bundle, monkeypatch, script_topic,
                                                                     script_data, review_payload, wav_bytes):
    from app.topics import topic_to_dict
    from app.video_renderer import RenderResult
    store, source_id, settings = bundle
    original = store.path(source_id)
    script = parse_script(script_data, script_topic, settings)
    monkeypatch.setattr("app.script_review.request_json", Mock(return_value=review_payload(script, script_topic, settings)))
    review = review_script(script, script_topic, settings)
    monkeypatch.setattr("app.full_pipeline.collect_topics", Mock(return_value={"selected_topics": [topic_to_dict(script_topic)]}))
    monkeypatch.setattr("app.full_pipeline.generate_script", Mock(return_value=script))
    monkeypatch.setattr("app.full_pipeline.review_script", Mock(return_value=review))
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(1), "mock", "model", "voice")
    monkeypatch.setattr("app.tts_pipeline.create_tts_provider", Mock(return_value=provider))
    def render(*args, output_dir, **kwargs):
        output_dir.mkdir()
        for name in ("video.mp4", "render.json", "subtitles.ass"):
            shutil.copy2(original / name, output_dir / name)
        return RenderResult(output_dir / "video.mp4", output_dir / "render.json", 4)
    monkeypatch.setattr("app.full_pipeline.render_video", render)
    result = run_all(settings, Path("sources.yaml"))
    assert result["status"] == "ok" and result["publication_performed"] is False
    assert result["drafts"][0]["status"] == "awaiting_approval"
    folder = store.path(result["drafts"][0]["id"])
    assert read_json(folder / "state.json")["approval"] is None
    store.verify(folder.name)


@pytest.mark.parametrize("failure", ["review", "tts", "render"])
def test_live_pipeline_keeps_partial_draft_and_stops_at_failed_stage(monkeypatch, publish_settings, script_topic,
                                                                  script_data, review_payload, failure, wav_bytes):
    from app.script_review import ReviewIssue
    from app.topics import topic_to_dict
    script = parse_script(script_data, script_topic, publish_settings)
    monkeypatch.setattr("app.script_review.request_json", Mock(return_value=review_payload(script, script_topic, publish_settings)))
    review = review_script(script, script_topic, publish_settings)
    if failure == "review":
        review = replace(review, issues=(ReviewIssue("fixture_mismatch", "Тестовое расхождение"),))
    monkeypatch.setattr("app.full_pipeline.collect_topics", Mock(return_value={"selected_topics": [topic_to_dict(script_topic)]}))
    monkeypatch.setattr("app.full_pipeline.generate_script", Mock(return_value=script))
    monkeypatch.setattr("app.full_pipeline.review_script", Mock(return_value=review))
    provider = Mock(spec=TTSProvider)
    provider.synthesize.return_value = SynthesizedSpeech(wav_bytes(1), "mock", "model", "voice")
    monkeypatch.setattr("app.tts_pipeline.create_tts_provider", Mock(return_value=provider))
    if failure == "tts":
        provider.synthesize.side_effect = RuntimeError("fixture failure")
    renderer = Mock(side_effect=RuntimeError("fixture render failure"))
    monkeypatch.setattr("app.full_pipeline.render_video", renderer)
    result = run_all(publish_settings, Path("sources.yaml"))
    item = result["drafts"][0]
    folder = ReelDrafts(publish_settings).path(item["id"])
    assert result["status"] == "partial" and (folder / "script.json").exists()
    assert (folder / "caption.txt").exists() and (folder / "sources.json").exists()
    assert read_json(folder / "state.json")["approval"] is None
    if failure == "review":
        assert item["status"] == "quarantined"
        provider.synthesize.assert_not_called()
        renderer.assert_not_called()
    elif failure == "tts":
        renderer.assert_not_called()
    else:
        assert (folder / "audio.wav").exists() and (folder / "timings.json").exists()


def test_real_stub_cli_creates_valid_mp4_and_cannot_be_approved(monkeypatch, publish_settings, tmp_path, capsys):
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        pytest.skip("Run in the FFmpeg Docker image")
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=publish_settings))
    monkeypatch.setattr("app.full_pipeline.collect_topics", Mock(side_effect=AssertionError("No network")))
    monkeypatch.setattr("app.full_pipeline.generate_script", Mock(side_effect=AssertionError("No LLM")))
    monkeypatch.setattr("app.tts_pipeline.create_tts_provider", Mock(side_effect=AssertionError("No ElevenLabs")))
    assert main(["run-all", "--stub"]) == 0
    result = json.loads(capsys.readouterr().out)
    item = result["drafts"][0]
    assert item["status"] == "stub_preview"
    folder, manifest, _ = ReelDrafts(publish_settings).verify(item["id"])
    assert manifest["mode"] == "stub" and (folder / "video.mp4").stat().st_size > 1000
    assert main(["approve", item["id"]]) == 2
    assert main(["publish", item["id"]]) == 2
    assert "ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ" in (folder / "subtitles.ass").read_text()
    import os
    if destination := os.environ.get("STUB_DEMO_DIR"):
        shutil.copytree(folder, Path(destination) / "stub-demo", dirs_exist_ok=True)
