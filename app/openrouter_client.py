"""Reusable JSON transport extracted from the former editorial pipeline."""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRYABLE_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class OpenRouterError(RuntimeError):
    """A request exhausted its attempts or cannot be retried."""


def parse_strict_json_object(content: str) -> dict[str, Any]:
    """Accept exactly one JSON object, without fences, duplicate keys or NaN."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise ValueError("Non-finite JSON constant")

    def floating(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number

    result = json.loads(content, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("OpenRouter did not return a JSON object") from exc
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as inner_exc:
            raise ValueError("OpenRouter did not return a JSON object") from inner_exc
    if not isinstance(data, dict):
        raise ValueError("OpenRouter returned non-object JSON")
    return data


def _retry_delay(settings: Settings, attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        try:
            seconds = float(response.headers.get("Retry-After", ""))
            if math.isfinite(seconds):
                return max(0.0, min(seconds, settings.retry_max_seconds))
        except ValueError:
            pass
    delay = settings.retry_base_seconds
    for _ in range(attempt):
        delay = min(settings.retry_max_seconds, delay * 2)
        if delay >= settings.retry_max_seconds:
            break
    return delay


def request_json(
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    schema: dict[str, Any] | None = None,
    schema_name: str = "legal_draft",
    strict_json: bool = False,
    validator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Request JSON explicitly; no default prompt or legal assertions are supplied.

    Structured output is a transport contract, not legal verification. Callers
    must validate returned fields and source grounding before saving a draft.
    """
    config = settings if settings is not None else Settings.from_env()
    if not config.openrouter_api_key:
        raise OpenRouterError("OPENROUTER_API_KEY is not configured")
    if not messages:
        raise ValueError("At least one message is required")
    models = list(dict.fromkeys((config.openrouter_model, *config.openrouter_fallback_models)))
    payload: dict[str, Any] = {
        "model": config.openrouter_model,
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": 5000,
        "response_format": {"type": "json_object"},
    }
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        }
    if len(models) > 1:
        payload.update(models=models, route="fallback")
    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "X-Title": "Legal Reels Agent",
    }

    for attempt in range(config.openrouter_max_attempts):
        response: httpx.Response | None = None
        reason = "invalid_response"
        try:
            response = httpx.post(
                OPENROUTER_URL, headers=headers, json=payload,
                timeout=config.openrouter_timeout,
            )
            if response.status_code >= 400:
                if response.status_code not in RETRYABLE_STATUSES:
                    raise OpenRouterError(f"OpenRouter HTTP {response.status_code}; request rejected")
                reason = f"http_{response.status_code}"
            else:
                data = response.json()
                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("Missing completion")
                message = choices[0].get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Empty completion")
                result = (parse_strict_json_object(content) if strict_json else parse_json_object(content))
                if validator is not None:
                    # Schema and content failures share the transport attempt budget.
                    validator(result)
                logger.info("OpenRouter JSON received on attempt %d", attempt + 1)
                return result
        except httpx.TransportError:
            reason = "transport_error"
        except ValueError:
            reason = "invalid_json_or_content"
            if strict_json or validator is not None:
                # Safe repair guidance: never echo rejected output or exception text.
                payload["messages"] = [*messages, {"role": "user", "content": (
                    "Предыдущий ответ не прошёл проверку JSON или содержания. "
                    "Верни заново только объект по схеме. Проверь все поля, ограничения "
                    "длины, структуру и дословное сохранение источников и CTA из задания."
                )}]

        if attempt + 1 < config.openrouter_max_attempts:
            delay = _retry_delay(config, attempt, response)
            logger.warning(
                "OpenRouter %s; retry %d/%d in %.1fs", reason,
                attempt + 2, config.openrouter_max_attempts, delay,
            )
            time.sleep(delay)
    # Providers can echo credentials and input material in error responses.
    raise OpenRouterError(f"OpenRouter request failed after {config.openrouter_max_attempts} attempts")
