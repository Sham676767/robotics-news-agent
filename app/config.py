"""Validated environment configuration; importing this module has no side effects."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values
from app.publishing_config import PublishingSettings


@dataclass(frozen=True, slots=True)
class Settings:
    publishing: PublishingSettings = field(default_factory=PublishingSettings)
    app_env: str = "development"
    log_level: str = "INFO"
    drafts_dir: Path = Path("drafts")
    openrouter_api_key: str = field(default="", repr=False)
    openrouter_model: str = "openai/gpt-4.1-mini"
    openrouter_fallback_models: tuple[str, ...] = ()
    openrouter_timeout: float = 120.0
    openrouter_max_attempts: int = 3
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 20.0
    script_cta: str = "Сохраните ролик и поделитесь им"
    tts_provider: str = "elevenlabs"
    tts_output_dir: Path = Path("audio")
    tts_timeout: float = 120.0
    tts_max_attempts: int = 3
    tts_retry_base_seconds: float = 2.0
    tts_retry_max_seconds: float = 20.0
    elevenlabs_api_key: str = field(default="", repr=False)
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    render_output_dir: Path = Path("renders")
    render_template: Path = Path("templates/default.yaml")
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    def __post_init__(self) -> None:
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        if not self.openrouter_model.strip():
            raise ValueError("OPENROUTER_MODEL must not be empty")
        if not self.script_cta.strip() or "\n" in self.script_cta or "\r" in self.script_cta:
            raise ValueError("SCRIPT_CTA must be a non-empty single line")
        if self.openrouter_max_attempts < 1:
            raise ValueError("OPENROUTER_MAX_ATTEMPTS must be positive")
        if not math.isfinite(self.openrouter_timeout) or self.openrouter_timeout <= 0:
            raise ValueError("OPENROUTER_TIMEOUT must be finite and positive")
        for name, value in (
            ("OPENROUTER_RETRY_BASE_SECONDS", self.retry_base_seconds),
            ("OPENROUTER_RETRY_MAX_SECONDS", self.retry_max_seconds),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("OPENROUTER_RETRY_MAX_SECONDS must be >= base delay")
        if not self.tts_provider.strip() or not self.elevenlabs_model_id.strip():
            raise ValueError("TTS_PROVIDER and ELEVENLABS_MODEL_ID must not be empty")
        if type(self.tts_max_attempts) is not int or self.tts_max_attempts < 1:
            raise ValueError("TTS_MAX_ATTEMPTS must be a positive integer")
        if not math.isfinite(self.tts_timeout) or self.tts_timeout <= 0:
            raise ValueError("TTS_TIMEOUT must be finite and positive")
        if any(not math.isfinite(value) or value < 0 for value in
               (self.tts_retry_base_seconds, self.tts_retry_max_seconds)):
            raise ValueError("TTS retry delays must be finite and non-negative")
        if self.tts_retry_max_seconds < self.tts_retry_base_seconds:
            raise ValueError("TTS_RETRY_MAX_SECONDS must be >= base delay")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        # Read only this project's .env, without changing the process environment.
        env = ({**{key: value for key, value in dotenv_values(Path(".env"), interpolate=False).items()
                   if value is not None}, **os.environ} if environ is None else environ)
        drafts_dir = env.get("DRAFTS_DIR", "drafts").strip()
        if not drafts_dir:
            raise ValueError("DRAFTS_DIR must not be empty")
        tts_output_dir = env.get("TTS_OUTPUT_DIR", "audio").strip()
        if not tts_output_dir:
            raise ValueError("TTS_OUTPUT_DIR must not be empty")
        try:
            attempts = int(env.get("OPENROUTER_MAX_ATTEMPTS", "3"))
            timeout = float(env.get("OPENROUTER_TIMEOUT", "120"))
            base = float(env.get("OPENROUTER_RETRY_BASE_SECONDS", "2"))
            maximum = float(env.get("OPENROUTER_RETRY_MAX_SECONDS", "20"))
            tts_timeout = float(env.get("TTS_TIMEOUT", "120"))
            tts_attempts = int(env.get("TTS_MAX_ATTEMPTS", "3"))
            tts_base = float(env.get("TTS_RETRY_BASE_SECONDS", "2"))
            tts_maximum = float(env.get("TTS_RETRY_MAX_SECONDS", "20"))
        except ValueError as exc:
            raise ValueError("API attempts/timeout/delays must be numeric") from exc
        for name in ("RENDER_OUTPUT_DIR", "RENDER_TEMPLATE", "FFMPEG_BIN", "FFPROBE_BIN"):
            if not env.get(name, "default").strip():
                raise ValueError(f"{name} must not be empty")
        return cls(
            publishing=PublishingSettings.from_env(env),
            app_env=env.get("APP_ENV", "development"),
            log_level=env.get("LOG_LEVEL", "INFO").strip().upper(),
            drafts_dir=Path(drafts_dir),
            openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip(),
            openrouter_model=env.get("OPENROUTER_MODEL", "openai/gpt-4.1-mini").strip(),
            openrouter_fallback_models=tuple(dict.fromkeys(
                model.strip()
                for model in env.get("OPENROUTER_FALLBACK_MODELS", "").split(",")
                if model.strip()
            )),
            openrouter_timeout=timeout,
            openrouter_max_attempts=attempts,
            retry_base_seconds=base,
            retry_max_seconds=maximum,
            script_cta=env.get("SCRIPT_CTA", "Сохраните ролик и поделитесь им").strip(),
            render_output_dir=Path(env.get("RENDER_OUTPUT_DIR", "renders")),
            render_template=Path(env.get("RENDER_TEMPLATE", "templates/default.yaml")),
            ffmpeg_bin=env.get("FFMPEG_BIN", "ffmpeg").strip(),
            ffprobe_bin=env.get("FFPROBE_BIN", "ffprobe").strip(),
            tts_provider=env.get("TTS_PROVIDER", "elevenlabs").strip().lower(),
            tts_output_dir=Path(tts_output_dir), tts_timeout=tts_timeout,
            tts_max_attempts=tts_attempts, tts_retry_base_seconds=tts_base,
            tts_retry_max_seconds=tts_maximum,
            elevenlabs_api_key=env.get("ELEVENLABS_API_KEY", "").strip(),
            elevenlabs_voice_id=env.get("ELEVENLABS_VOICE_ID", "").strip(),
            elevenlabs_model_id=env.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip(),
        )
