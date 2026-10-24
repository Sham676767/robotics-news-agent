"""Read-only dry run: validate configuration and estimate calls, never instantiate APIs."""
from __future__ import annotations

import math
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from app.config import Settings
from app.publishing_config import public_video_url
from app.render_template import load_render_template
from app.source_config import load_source_config


def writable_destination(path: Path) -> bool:
    candidate = path.absolute()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def dry_run(settings: Settings, sources: Path, *, count: int = 1, stub: bool = False,
            clips_dir: Path | None = None) -> dict[str, Any]:
    issues: list[str] = []
    mode = "stub" if stub or settings.publishing.pipeline_mode == "stub" else "live"
    if not 1 <= count <= 10:
        issues.append("Число роликов должно быть от 1 до 10")
    config = None
    try:
        config = load_source_config(sources)
    except (ValueError, OSError):
        issues.append("sources.yaml отсутствует или не прошёл проверку")
    theme = None
    try:
        theme = load_render_template(settings.render_template)
    except (ValueError, OSError):
        issues.append("Шаблон оформления отсутствует или не прошёл проверку")
    for name, tool in (("ffmpeg", settings.ffmpeg_bin), ("ffprobe", settings.ffprobe_bin)):
        if not shutil.which(tool):
            issues.append(f"Не найден {name}")
    if shutil.which(settings.ffmpeg_bin):
        try:
            result = subprocess.run([settings.ffmpeg_bin, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=15)
            if result.returncode or not re.search(r"\bass\s+V->V", result.stdout):
                issues.append("FFmpeg не содержит фильтр ass/libass")
        except (OSError, subprocess.TimeoutExpired):
            issues.append("Не удалось проверить фильтры FFmpeg")
    if theme:
        font_tool = shutil.which("fc-match")
        if not font_tool:
            issues.append("Не найден fc-match для проверки шрифта; используйте Docker-образ проекта")
        else:
            try:
                font = subprocess.run([font_tool, "-f", "%{family}", theme.font], capture_output=True, text=True, timeout=10)
                if font.returncode or theme.font.casefold() not in font.stdout.casefold():
                    issues.append("Шрифт из шаблона не установлен")
            except (OSError, subprocess.TimeoutExpired):
                issues.append("Не удалось проверить шрифт")
    folders = [settings.drafts_dir, settings.tts_output_dir, settings.render_output_dir]
    if config:
        folders.extend((config.history_path.parent, config.output_path.parent))
    if any(not writable_destination(folder) for folder in folders):
        issues.append("Нет доступа к папке черновиков, аудио, видео или данных")
    if clips_dir is not None:
        clips = ([path for path in clips_dir.iterdir() if path.is_file() and path.suffix.lower() in
                  {".mp4", ".mov", ".mkv", ".webm"}] if clips_dir.is_dir() else [])
        if not 1 <= len(clips) <= 20 or any(not os.access(path, os.R_OK) for path in clips):
            issues.append("Папка фоновых клипов должна содержать 1–20 доступных видео")
    publication = settings.publishing
    if mode == "live":
        checks = (("OPENROUTER_API_KEY", settings.openrouter_api_key, r"sk-or-v1-[A-Za-z0-9_-]{12,}"),
                  ("ELEVENLABS_API_KEY", settings.elevenlabs_api_key, r"[A-Za-z0-9_-]{16,}"),
                  ("ELEVENLABS_VOICE_ID", settings.elevenlabs_voice_id, r"[A-Za-z0-9_-]{3,}"),
                  ("INSTAGRAM_ACCESS_TOKEN", publication.instagram_access_token, r"[A-Za-z0-9._~-]{20,}"),
                  ("S3_ACCESS_KEY", publication.s3_access_key, r"[^\s]{8,}"),
                  ("S3_SECRET_KEY", publication.s3_secret_key, r"[^\s]{16,}"))
        for name, value, pattern in checks:
            if not re.fullmatch(pattern, value):
                issues.append(f"{name}: отсутствует или имеет неподходящий формат")
        if settings.tts_provider != "elevenlabs":
            issues.append("Настроенный TTS_PROVIDER не поддерживается текущей реализацией")
        try:
            publication.require_account()
        except ValueError:
            issues.append("Нужны INSTAGRAM_USER_ID и INSTAGRAM_API_VERSION из настроек приложения Meta")
        try:
            publication.require_storage()
            public_video_url(publication.s3_public_base_url or publication.s3_endpoint)
            minimum = publication.poll_attempts * publication.poll_interval_seconds + publication.max_attempts * publication.api_timeout + 120
            if not publication.s3_public_base_url and publication.s3_presign_ttl_seconds < minimum:
                issues.append("S3_PRESIGN_TTL_SECONDS недостаточен для обработки видео")
        except ValueError:
            issues.append("Настройки S3 неполны/невалидны либо URL недоступен Instagram: нужен публичный HTTPS")
    used_count = 0
    if config and config.history_path.is_file():
        try:
            # mode=ro forbids creating a missing database or changing the history.
            with sqlite3.connect(config.history_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                used_count = connection.execute("SELECT COUNT(*) FROM used_topics").fetchone()[0]
        except sqlite3.Error:
            issues.append("Не удалось прочитать существующую историю тем")
    semantic = 0
    if config and mode == "live":
        chunks = math.ceil(config.max_candidates / config.semantic_batch_size)
        semantic = chunks * (chunks + 1) // 2 + chunks * math.ceil(used_count / config.semantic_batch_size)
    paid = {"generation": count, "source_review": count, "tts": count,
            "semantic_dedup_upper_bound": semantic,
            "max_openrouter_attempts": (semantic + 2 * count) * settings.openrouter_max_attempts,
            "max_tts_attempts": count * settings.tts_max_attempts} if mode == "live" else {"total": 0}
    return {"dry_run": True, "ready": not issues, "issues": issues, "mode": mode, "video_count": count,
            "model": settings.openrouter_model if mode == "live" else "local-stub",
            "voice_id": settings.elevenlabs_voice_id if mode == "live" else "local-tone",
            "stages": (["collect", "script", "source_review", "tts", "render", "save_draft", "wait_for_approve"]
                       if mode == "live" else ["fixture_script", "local_tone", "render", "save_stub_preview"]),
            "external_calls": (["RSS/HTML и первоисточники", "OpenRouter: дедупликация, сценарий и сверка", "ElevenLabs: озвучка"]
                               if mode == "live" else []),
            "after_manual_approval": (["S3 upload", "Instagram quota/media/status/media_publish", "optional S3 delete"]
                                      if mode == "live" else []),
            "paid_request_estimate": paid,
            "note": "Оценка зависит от числа тем и ретраев; это не цена. Ключи проверены только по формату, доступы и квоты без сети не подтверждены."}
