from pathlib import Path

import pytest

from app.config import Settings


def test_defaults_need_no_api_key():
    settings = Settings.from_env({})
    assert settings.openrouter_api_key == ""
    assert settings.drafts_dir == Path("drafts")


def test_loads_supported_environment_variables():
    settings = Settings.from_env({
        "APP_ENV": "test", "LOG_LEVEL": "debug", "DRAFTS_DIR": "custom/drafts",
        "OPENROUTER_API_KEY": "test-only-key", "OPENROUTER_MODEL": "test/model",
        "OPENROUTER_FALLBACK_MODELS": " test/backup, test/backup, ,test/other ",
        "OPENROUTER_TIMEOUT": "5", "OPENROUTER_MAX_ATTEMPTS": "4",
        "OPENROUTER_RETRY_BASE_SECONDS": "0", "OPENROUTER_RETRY_MAX_SECONDS": "1",
    })
    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.drafts_dir == Path("custom/drafts")
    assert settings.openrouter_fallback_models == ("test/backup", "test/other")
    assert settings.openrouter_timeout == 5
    assert settings.openrouter_max_attempts == 4
    assert settings.retry_base_seconds == 0
    assert settings.retry_max_seconds == 1
    assert "test-only-key" not in repr(settings)


@pytest.mark.parametrize(("key", "value"), [
    ("LOG_LEVEL", "unexpected"), ("DRAFTS_DIR", " "), ("OPENROUTER_MODEL", ""),
    ("OPENROUTER_MAX_ATTEMPTS", "0"), ("OPENROUTER_MAX_ATTEMPTS", "bad"),
    ("OPENROUTER_TIMEOUT", "0"), ("OPENROUTER_TIMEOUT", "inf"), ("OPENROUTER_TIMEOUT", "nan"),
    ("OPENROUTER_RETRY_BASE_SECONDS", "-1"), ("OPENROUTER_RETRY_BASE_SECONDS", "nan"),
    ("OPENROUTER_RETRY_MAX_SECONDS", "1"), ("OPENROUTER_RETRY_MAX_SECONDS", "inf"),
])
def test_invalid_configuration_fails_early(key, value):
    with pytest.raises(ValueError):
        Settings.from_env({key: value})


def test_example_environment_is_complete_and_valid():
    text = (Path(__file__).parents[1] / ".env.example").read_text()
    env = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))
    Settings.from_env(env)
