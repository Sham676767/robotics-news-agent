"""Validated environment configuration; importing this module has no side effects."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Settings:
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

    def __post_init__(self) -> None:
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        if not self.openrouter_model.strip():
            raise ValueError("OPENROUTER_MODEL must not be empty")
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

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        drafts_dir = env.get("DRAFTS_DIR", "drafts").strip()
        if not drafts_dir:
            raise ValueError("DRAFTS_DIR must not be empty")
        try:
            attempts = int(env.get("OPENROUTER_MAX_ATTEMPTS", "3"))
            timeout = float(env.get("OPENROUTER_TIMEOUT", "120"))
            base = float(env.get("OPENROUTER_RETRY_BASE_SECONDS", "2"))
            maximum = float(env.get("OPENROUTER_RETRY_MAX_SECONDS", "20"))
        except ValueError as exc:
            raise ValueError("OpenRouter attempts/timeout/delays must be numeric") from exc
        return cls(
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
        )
