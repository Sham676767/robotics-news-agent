"""Reviewable, self-contained bundles and durable publication state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.config import Settings
from app.openrouter_client import parse_strict_json_object
from app.render_inputs import load_render_audio
from app.script_review import digest, load_checked_script
from app.video_renderer import probe_media, verify_video

ASSETS = ("script.json", "script.review.json", "audio.wav", "timings.json", "video.mp4", "render.json",
          "subtitles.ass", "caption.txt", "sources.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic checkpoint: state must survive a crash after a network side effect."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    return parse_strict_json_object(path.read_text(encoding="utf-8"))


class ReelDrafts:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.drafts_dir / "reels"

    def path(self, reel_id: str) -> Path:
        if not isinstance(reel_id, str) or not re.fullmatch(r"reel-[0-9a-f]{32}", reel_id):
            raise ValueError("Invalid reel draft ID")
        path = self.root / reel_id
        if path.is_symlink():
            raise ValueError("Draft directories must not be symbolic links")
        return path

    def create(self, *, mode: str = "live") -> Path:
        folder = self.path(f"reel-{uuid4().hex}")
        folder.mkdir(parents=True)
        write_json(folder / "draft.json", {"schema_version": 1, "id": folder.name, "mode": mode,
                   "created_at": now_iso(), "stage": "preparing", "review_status": "pending", "assets": {}})
        write_json(folder / "state.json", {"status": "draft", "approval": None, "container_id": None,
                   "media_id": None, "storage": None, "last_error": None})
        return folder

    @contextmanager
    def locked(self) -> Iterator[None]:
        # A crash releases the OS/SQLite lock. No stale lock file can authorize a duplicate send.
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.root / ".publication-lock.sqlite3", timeout=0, isolation_level=None)
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                raise ValueError("Another approval/publication is running; try again after it finishes") from None
            yield
        finally:
            connection.close()

    def checkpoint(self, folder: Path, *, stage: str, review_status: str | None = None, error: str | None = None) -> None:
        data = read_json(folder / "draft.json")
        data["stage"] = stage
        if review_status is not None:
            data["review_status"] = review_status
        if error:
            data["error"] = error
        data["assets"] = {name: checksum(folder / name) for name in ASSETS if (folder / name).is_file()}
        write_json(folder / "draft.json", data)

    def finish(self, folder: Path) -> None:
        script, _, _ = load_checked_script(folder / "script.json", self.settings)
        # The final caption is reviewed as a whole by the human; no new legal assertions added.
        caption = "\n\n".join((script.caption, script.disclaimer, " ".join(script.hashtags)))
        if len(caption) > 2200:
            raise ValueError("Final Instagram caption is too long")
        (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
        write_json(folder / "sources.json", {"sources": script.to_dict()["sources"]})
        self.checkpoint(folder, stage="ready", review_status="checked")
        self.verify(folder.name)

    def verify(self, reel_id: str) -> tuple[Path, dict[str, Any], str]:
        folder = self.path(reel_id)
        manifest = read_json(folder / "draft.json")
        if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1 or manifest.get("id") != reel_id
                or manifest.get("stage") != "ready" or manifest.get("review_status") != "checked"
                or manifest.get("mode") not in ("live", "stub") or not isinstance(manifest.get("assets"), dict)
                or set(manifest["assets"]) != set(ASSETS)):
            raise ValueError("Draft is incomplete or its review did not pass")
        for name in ASSETS:
            path = folder / name
            if path.is_symlink() or checksum(path) != manifest["assets"][name]:
                raise ValueError("Draft files changed; rebuild and approve the new version")
        script, _, review = load_checked_script(folder / "script.json", self.settings)
        audio = load_render_audio(folder / "timings.json", script)
        render = read_json(folder / "render.json")
        try:
            expected = audio.duration + render["template"]["end_seconds"]
            if (render["script_sha256"] != digest(script.to_dict()) or render["audio_sha256"] != audio.sha256
                    or render["video_sha256"] != manifest["assets"]["video.mp4"]
                    or render["publication_allowed"] is not False or render["human_review_required"] is not True):
                raise ValueError
        except (KeyError, TypeError):
            raise ValueError("Render metadata does not match the reviewed assets") from None
        verify_video(probe_media(folder / "video.mp4", self.settings.ffprobe_bin), expected)
        if (folder / "video.mp4").stat().st_size > 1_000_000_000 or expected < 3:
            raise ValueError("Video exceeds Instagram file size or is too short")
        caption = "\n\n".join((script.caption, script.disclaimer, " ".join(script.hashtags))) + "\n"
        if (folder / "caption.txt").read_text(encoding="utf-8") != caption or len(caption.rstrip()) > 2200:
            raise ValueError("Caption does not match the reviewed script")
        if read_json(folder / "sources.json") != {"sources": script.to_dict()["sources"]}:
            raise ValueError("Sources do not match the reviewed script")
        if manifest["mode"] == "live" and review.requested_model == "local-stub":
            raise ValueError("Stub evidence cannot be used as a live review")
        return folder, manifest, digest(manifest)

    def prepare(self, script: Path, timings: Path, video: Path) -> str:
        folder = self.create()
        try:
            pairs = {"script.json": script, "script.review.json": script.with_suffix(".review.json"),
                     "audio.wav": timings.parent / "audio.wav", "timings.json": timings, "video.mp4": video,
                     "render.json": video.parent / "render.json", "subtitles.ass": video.parent / "subtitles.ass"}
            for name, source in pairs.items():
                shutil.copy2(source, folder / name)
            self.finish(folder)
        except (ValueError, OSError, RuntimeError):
            self.checkpoint(folder, stage="failed", error="preparation_failed")
            raise
        return folder.name

    def approve(self, reel_id: str) -> dict[str, Any]:
        with self.locked():
            folder, manifest, fingerprint = self.verify(reel_id)
            if manifest["mode"] != "live":
                raise ValueError("Stub drafts cannot be approved or published")
            self.settings.publishing.require_account(token=False)
            state = read_json(folder / "state.json")
            if state["status"] not in ("draft", "approved"):
                raise ValueError("Publication already started; approval cannot reset its state")
            state.update(status="approved", approval={"bundle_sha256": fingerprint, "approved_at": now_iso(),
                         "account": self.settings.publishing.account,
                         "share_to_feed": self.settings.publishing.instagram_share_to_feed})
            write_json(folder / "state.json", state)
            return {"id": reel_id, "status": "approved", "account": self.settings.publishing.account}
