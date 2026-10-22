import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import main

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/legal_draft.json"


def test_default_run_has_no_external_effects(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DRAFTS_DIR", str(tmp_path / "drafts"))
    assert main([]) == 0
    assert not (tmp_path / "drafts").exists()


def test_cli_validates_and_saves_existing_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAFTS_DIR", str(tmp_path))
    assert main(["--draft", str(FIXTURE)]) == 0
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["status"] == "review_required"


@pytest.mark.parametrize("kind", ["missing", "malformed", "non_utf8"])
def test_cli_reports_bad_input(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("DRAFTS_DIR", str(tmp_path / "out"))
    path = tmp_path / "input.json"
    if kind == "malformed":
        path.write_text("{broken")
    elif kind == "non_utf8":
        path.write_bytes(b"\xff\xfe")
    assert main(["--draft", str(path)]) == 2
    assert not (tmp_path / "out").exists()


def test_cli_reports_bad_configuration(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    assert main([]) == 2


@pytest.mark.parametrize("entrypoint", [["main.py"], ["-m", "app"]])
def test_both_entrypoints_work_offline(entrypoint, tmp_path):
    # The subprocess runs from an empty directory with a read-only socket guard.
    guard = tmp_path / "sitecustomize.py"
    guard.write_text(
        "import socket\n"
        "def blocked(*a, **kw): raise AssertionError('network disabled')\n"
        "socket.socket.connect = blocked\n"
        "socket.create_connection = blocked\n"
    )
    if entrypoint == ["main.py"]:
        entrypoint = [str(ROOT / "main.py")]
    result = subprocess.run(
        [sys.executable, *entrypoint], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(tmp_path), str(ROOT))), "LOG_LEVEL": "INFO"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "configuration valid" in result.stderr
