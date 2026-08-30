from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"


def build_ranking_prompt(items: list[dict[str, Any]]) -> str:
    compact = [
        {
            "id": item["id"],
            "title": item["title"],
            "source": item["source"],
            "published_at": item.get("published_at"),
            "summary": item.get("summary", "")[:1200],
            "topics": item.get("topics", []),
        }
        for item in items
    ]
    return (
        "Ты редактор новостного проекта о робототехнике. "
        "Выбери до 5 самых интересных и потенциально вирусных событий. "
        "Не придумывай факты. Оценивай новизну, общественный интерес, "
        "технологическую значимость, свежесть и качество источника. "
        "Верни только JSON-массив объектов с полями id, score, reason.\n\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def _extract_json(text: str) -> Any:
    """Parse JSON even when a free model adds prose or markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Recover the first complete JSON array/object embedded in model prose.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"AI did not return parseable JSON: {text[:500]!r}")


def _heuristic_fallback(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emergency fallback: keep the pipeline alive if a free model is unavailable."""
    ranked = sorted(
        items,
        key=lambda item: (
            len(item.get("summary", "")),
            len(item.get("topics", [])),
        ),
        reverse=True,
    )
    return [
        {"id": item["id"], "score": 0, "reason": "AI ranking unavailable; deterministic fallback"}
        for item in ranked[:5]
    ]


def rank_with_deepseek(items: list[dict[str, Any]], api_key: str | None = None) -> list[dict[str, Any]]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    if not items:
        return []

    payload = {
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": "Отвечай только валидным JSON без markdown и пояснений."},
            {"role": "user", "content": build_ranking_prompt(items)},
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "Robotics News Agent",
    }

    last_error: str | None = None
    # Several attempts are intentional: openrouter/free may route each request
    # to a different free provider/model, so a transient provider failure should
    # not kill the daily pipeline.
    for attempt in range(5):
        try:
            response = httpx.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=90,
            )
            if response.status_code in (408, 409, 429, 500, 502, 503, 504):
                last_error = response.text[:1000]
                if attempt < 4:
                    time.sleep(min(5 * (attempt + 1), 20))
                    continue
            response.raise_for_status()
            data = response.json()

            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(
                    f"OpenRouter returned no choices: {json.dumps(data, ensure_ascii=False)[:1000]}"
                )

            message = choices[0].get("message") or {}
            content = message.get("content")
            if not content:
                refusal = message.get("refusal")
                finish_reason = choices[0].get("finish_reason")
                raise RuntimeError(
                    "OpenRouter returned empty content "
                    f"(finish_reason={finish_reason!r}, refusal={refusal!r}, model={data.get('model')!r})"
                )

            result = _extract_json(content)
            if not isinstance(result, list):
                raise ValueError("AI returned non-list JSON")
            valid = [item for item in result if isinstance(item, dict) and "id" in item]
            if not valid:
                raise ValueError("AI returned no usable ranking items")
            return valid[:5]
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt < 4:
                time.sleep(min(5 * (attempt + 1), 20))
                continue

    print(f"Warning: OpenRouter ranking unavailable after 5 attempts: {last_error}")
    print("Using deterministic ranking fallback so the daily pipeline can continue.")
    return _heuristic_fallback(items)
