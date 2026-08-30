from __future__ import annotations

import json
import os
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


def rank_with_deepseek(items: list[dict[str, Any]], api_key: str | None = None) -> list[dict[str, Any]]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    if not items:
        return []

    payload = {
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": "Отвечай только валидным JSON без markdown."},
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
    for attempt in range(3):
        try:
            response = httpx.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = response.text[:1000]
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
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

            text = content.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                lines = lines[1:] if lines and lines[0].startswith("```") else lines
                lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
                text = "\n".join(lines).strip()

            result = json.loads(text)
            if not isinstance(result, list):
                raise ValueError("AI returned non-list JSON")
            return result[:5]
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"OpenRouter ranking failed after 3 attempts: {last_error}") from exc

    raise RuntimeError(f"OpenRouter ranking failed: {last_error}")
