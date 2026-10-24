"""Offline readiness checks: real fixture configuration, failures and no side effects."""
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from app.cli import main
from app.config import Settings
from app.pipeline_preflight import dry_run
from app.source_config import load_source_config
from app.topic_history import TopicHistory

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def offline_project(tmp_path, monkeypatch):
    shutil.copy2(ROOT / "tests/fixtures/preflight.env", tmp_path / ".env")
    shutil.copy2(ROOT / "tests/fixtures/preflight.yaml", tmp_path / "sources.yaml")
    (tmp_path / "templates").mkdir()
    shutil.copy2(ROOT / "templates/default.yaml", tmp_path / "templates/default.yaml")
    # Isolate from the developer's real credentials and output paths.
    for name in tuple(os.environ):
        if name.startswith(("OPENROUTER_", "ELEVENLABS_", "INSTAGRAM_", "S3_", "TTS_", "RENDER_")) or name in {
            "PIPELINE_MODE", "DRAFTS_DIR", "FFMPEG_BIN", "FFPROBE_BIN", "SCRIPT_CTA", "LOG_LEVEL",
        }:
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    return tmp_path, Settings.from_env()


@pytest.fixture
def local_tools(monkeypatch):
    monkeypatch.setattr("app.pipeline_preflight.shutil.which", Mock(return_value="/fixture/tool"))
    runner = Mock(side_effect=lambda args, **kwargs: Mock(
        returncode=0, stdout=" ass V->V " if "-filters" in args else "DejaVu Sans"))
    monkeypatch.setattr("app.pipeline_preflight.subprocess.run", runner)
    return runner


def snapshot(root):
    return {str(path.relative_to(root)): (path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
            for path in root.rglob("*")}


def test_cli_fixture_plan_and_existing_history_are_read_only(offline_project, local_tools, script_topic,
                                                            monkeypatch, capsys):
    root, _ = offline_project
    with TopicHistory(Path("data/topic_history.sqlite3")) as history:
        history.save_selected([script_topic])
        history.mark_used([script_topic.id])
    clients = []
    for target in ("app.full_pipeline.collect_topics", "app.full_pipeline.generate_script",
                   "app.tts_pipeline.create_tts_provider", "app.instagram_publisher.InstagramClient",
                   "app.instagram_publisher.S3VideoStorage"):
        client = Mock(side_effect=AssertionError("No external clients in dry-run"))
        monkeypatch.setattr(target, client)
        clients.append(client)
    before = snapshot(root)
    assert main(["run-all", "--dry-run", "--count", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] and report["mode"] == "live" and report["video_count"] == 2
    assert report["stages"][-1] == "wait_for_approve"
    assert report["paid_request_estimate"]["semantic_dedup_upper_bound"] == 2
    assert report["paid_request_estimate"]["generation"] == report["paid_request_estimate"]["tts"] == 2
    assert report["model"] == "fixture/model" and report["voice_id"] == "fixture-voice"
    assert report["external_calls"] and report["after_manual_approval"]
    assert snapshot(root) == before
    for client in clients:
        client.assert_not_called()


def test_actual_cli_entry_point_with_real_tools_and_blocked_network(offline_project):
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe", "fc-match")):
        pytest.skip("Run in the FFmpeg Docker image")
    root, _ = offline_project
    before = snapshot(root)
    # A separate interpreter exercises .env loading and actual media/font probes.
    code = """
import runpy, socket, sys
def blocked(*args, **kwargs):
    raise AssertionError('Network forbidden during offline preflight')
socket.socket.connect = blocked
socket.create_connection = blocked
sys.argv = ['app', 'run-all', '--dry-run', '--count', '2']
runpy.run_module('app', run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=root,
                            env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ready"] and report["video_count"] == 2
    assert snapshot(root) == before


@pytest.mark.parametrize("count", [0, 11])
def test_invalid_count_is_reported(offline_project, local_tools, count):
    _, settings = offline_project
    assert not dry_run(settings, Path("sources.yaml"), count=count)["ready"]


@pytest.mark.parametrize("payload", ["[broken", "[]", "sources: []", "disabled"])
def test_missing_invalid_or_disabled_sources_fail_preflight(offline_project, local_tools, payload):
    _, settings = offline_project
    path = Path("sources.yaml")
    if payload == "disabled":
        config = yaml.safe_load(path.read_text())
        config["sources"][0]["enabled"] = False
        path.write_text(yaml.safe_dump(config))
        with pytest.raises(ValueError, match="enabled source"):
            load_source_config(path)
    else:
        path.write_text(payload)
    result = dry_run(settings, path)
    assert not result["ready"] and any("sources.yaml" in issue for issue in result["issues"])


def test_missing_sources_and_template_are_reported(offline_project, local_tools):
    _, settings = offline_project
    result = dry_run(replace(settings, render_template=Path("missing.yaml")), Path("missing-sources.yaml"))
    assert not result["ready"] and len(result["issues"]) == 2


@pytest.mark.parametrize("failure", ["no_ass", "filters_exit", "filters_timeout", "font_exit", "font_timeout", "no_font"])
def test_media_tool_and_font_problems(offline_project, local_tools, monkeypatch, failure):
    _, settings = offline_project
    def run(args, **kwargs):
        filters = "-filters" in args
        if failure == "filters_timeout" and filters or failure == "font_timeout" and not filters:
            raise subprocess.TimeoutExpired(args, 1)
        bad_exit = failure == "filters_exit" and filters or failure == "font_exit" and not filters
        return Mock(returncode=int(bad_exit), stdout="" if failure == "no_ass" and filters
                    else " ass V->V " if filters else "DejaVu Sans")
    local_tools.side_effect = run
    if failure == "no_font":
        monkeypatch.setattr("app.pipeline_preflight.shutil.which", lambda name: None if name == "fc-match" else "/fixture/tool")
    assert not dry_run(settings, Path("sources.yaml"))["ready"]


def test_unwritable_output_and_invalid_clip_folder(offline_project, local_tools, monkeypatch):
    _, settings = offline_project
    monkeypatch.setattr("app.pipeline_preflight.os.access", Mock(return_value=False))
    result = dry_run(settings, Path("sources.yaml"), clips_dir=Path("missing-clips"))
    assert not result["ready"] and len(result["issues"]) == 2


def test_existing_clip_folder_is_only_read(offline_project, local_tools):
    root, settings = offline_project
    clips = root / "clips"
    clips.mkdir()
    (clips / "fixture.mp4").write_bytes(b"Placeholder; dry-run checks access, not media decoding")
    before = snapshot(root)
    assert dry_run(settings, Path("sources.yaml"), clips_dir=clips)["ready"]
    assert snapshot(root) == before


def test_broken_history_is_reported_without_repair(offline_project, local_tools):
    root, settings = offline_project
    (root / "data").mkdir()
    Path("data/topic_history.sqlite3").write_bytes(b"not SQLite")
    before = snapshot(root)
    result = dry_run(settings, Path("sources.yaml"))
    assert not result["ready"] and any("историю" in issue for issue in result["issues"])
    assert snapshot(root) == before


def test_unknown_tts_and_short_presign_are_reported(offline_project, local_tools):
    _, settings = offline_project
    publication = replace(settings.publishing, s3_presign_ttl_seconds=600, poll_attempts=10)
    result = dry_run(replace(settings, publishing=publication, tts_provider="unavailable"), Path("sources.yaml"))
    assert not result["ready"] and len(result["issues"]) == 2


def test_environment_selects_stub_and_no_paid_requests(offline_project, local_tools, monkeypatch, capsys):
    root, _ = offline_project
    monkeypatch.setenv("PIPELINE_MODE", "stub")
    before = snapshot(root)
    monkeypatch.setattr(sys, "argv", ["app", "run-all", "--dry-run"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("app", run_name="__main__")
    assert result.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "stub" and report["paid_request_estimate"] == {"total": 0}
    assert report["external_calls"] == report["after_manual_approval"] == []
    assert snapshot(root) == before
