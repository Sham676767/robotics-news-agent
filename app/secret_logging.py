"""Redact configured credentials and suppress HTTP/SDK debug wire logs."""
from __future__ import annotations

import logging
import re

from app.config import Settings


class SecretFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self.secrets = tuple(sorted((value for value in secrets if value), key=len, reverse=True))

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"https?://[^\s]+[?][^\s]+", "[URL_WITH_QUERY_REDACTED]", text)
        record.msg, record.args = text, ()
        if record.exc_info:
            record.exc_info, record.exc_text = None, None
        return True


def protect_logs(settings: Settings) -> None:
    publication = settings.publishing
    filter_ = SecretFilter((settings.openrouter_api_key, settings.elevenlabs_api_key,
                            publication.instagram_access_token, publication.s3_access_key, publication.s3_secret_key))
    for handler in logging.getLogger().handlers:
        for existing in tuple(handler.filters):
            if isinstance(existing, SecretFilter):
                handler.removeFilter(existing)
        handler.addFilter(filter_)
    for name in ("httpx", "httpcore", "boto3", "botocore", "s3transfer", "urllib3"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
