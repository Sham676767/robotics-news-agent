from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"


def build_ranking_prompt(items: list[dict[str, Any]], limit: int = 5) -> str:
    compact = [{"id": i["id"], "title": i["title"], "source": i["source"], "published_at": i.get("published_at"), "summary": i.get("summary", "")[:1200], "topics": i.get("topics", [])} for i in items]
    return ("Ты редактор новостного проекта о робототехнике. "
            f"Ранжируй до {limit} самых интересных событий. Не придумывай факты. "
            "Оценивай новизну, общественный интерес, технологическую значимость, свежесть и качество источника. "
            "Верни только JSON-массив объектов с полями id, score, reason.\n\n" + json.dumps(compact, ensure_ascii=False))


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"AI did not return parseable JSON: {text[:500]!r}")


def _heuristic_fallback(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(items, key=lambda item: (len(item.get("summary", "")), len(item.get("topics", []))), reverse=True)
    return [{"id": item["id"], "score": 0, "reason": "AI ranking unavailable; deterministic fallback"} for item in ranked[:limit]]


def rank_with_deepseek(items: list[dict[str, Any]], api_key: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not items:
        return []
    limit = max(1, min(limit, len(items)))
    if not key:
        print("Warning: OPENROUTER_API_KEY is not configured; using deterministic ranking fallback.")
        return _heuristic_fallback(items, limit=limit)

    payload = {
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": "Отвечай только валидным JSON без markdown и пояснений."},
            {"role": "user", "content": build_ranking_prompt(items, limit=limit)},
        ],
        "temperature": 0.1,
        "max_tokens": max(1200, limit * 220),
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Robotics News Agent"}

    last_error: str | None = None
    for attempt in range(2):
        try:
            response = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
            if response.status_code == 429:
                print("Warning: OpenRouter rate limit (429); using deterministic ranking fallback immediately.")
                return _heuristic_fallback(items, limit=limit)
            if response.status_code in (408, 409, 500, 502, 503, 504) and attempt == 0:
                last_error = response.text[:1000]
                time.sleep(2)
                continue
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"OpenRouter returned no choices: {json.dumps(data, ensure_ascii=False)[:1000]}")
            message = choices[0].get("message") or {}
            content = message.get("content")
            if not content:
                raise RuntimeError("OpenRouter returned empty ranking content")
            result = _extract_json(content)
            if not isinstance(result, list):
                raise ValueError("AI returned non-list JSON")
            valid = [item for item in result if isinstance(item, dict) and "id" in item]
            if not valid:
                raise ValueError("AI returned no usable ranking items")
            return valid[:limit]
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt == 0:
                time.sleep(2)
                continue

    print(f"Warning: OpenRouter ranking unavailable after 2 attempts: {last_error}")
    return _heuristic_fallback(items, limit=limit)
