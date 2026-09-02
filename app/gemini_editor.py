from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.article_editor import (
    ARTICLE_SCHEMA,
    SYSTEM_PROMPT,
    _attach_sources,
    _normalize_article,
    _parse_json,
    validate_article,
)
from app.language_guard import validate_russian_article

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _gemini_schema() -> dict[str, Any]:
    def convert(node: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {"type": node["type"].upper()}
        if "properties" in node:
            result["properties"] = {k: convert(v) for k, v in node["properties"].items()}
        if "items" in node:
            result["items"] = convert(node["items"])
        if "required" in node:
            result["required"] = node["required"]
        return result

    return convert(ARTICLE_SCHEMA)


def _request_gemini(prompt: str, api_key: str, model: str) -> str:
    url = GEMINI_URL.format(model=model)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.15,
            "maxOutputTokens": 5000,
            "responseMimeType": "application/json",
            "responseSchema": _gemini_schema(),
        },
    }
    response = httpx.post(
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data, ensure_ascii=False)[:1500]}")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "".join(str(part.get("text") or "") for part in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini returned empty article content: {json.dumps(data, ensure_ascii=False)[:1500]}")
    return text


def generate_article(top5: list[dict[str, Any]], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if len(top5) != 5:
        raise ValueError("Article editor requires exactly 5 selected stories")

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    prompt = (
        "Подготовь одну профессиональную публикацию-дайджест из этих пяти новостей. "
        "Не меняй порядок карточек. Для каждого блока используй только факты соответствующей карточки. "
        "ВЕСЬ РЕДАКЦИОННЫЙ ТЕКСТ ОБЯЗАТЕЛЬНО ПИШИ НА РУССКОМ ЯЗЫКЕ: title, intro, headline и body. "
        "Не используй английские предложения или английские заголовки; английскими могут оставаться только оригинальные названия компаний, продуктов, проектов и технические обозначения. "
        "Верни ровно 5 items с headline и body. НЕ добавляй card_index, source или url — это служебные поля, их добавит программа по порядку карточек. "
        "Особенно строго отделяй факт от интерпретации и не повышай заявленную степень технологической готовности. "
        "Перед выдачей проверь числа, названия, стадии внедрения, русский язык каждого поля и соответствие каждого блока своей карточке.\n\n"
        + json.dumps(top5, ensure_ascii=False, indent=2)
    )

    draft_content = _request_gemini(prompt, key, model)
    try:
        draft = _normalize_article(_parse_json(draft_content))
        validate_article(draft, top5)
        validate_russian_article(_attach_sources(draft, top5))
        return _attach_sources(draft, top5)
    except (ValueError, RuntimeError) as first_error:
        repair_prompt = (
            "Исправь ТОЛЬКО ошибки в черновике статьи ниже. Не переписывай удачные части без необходимости. "
            "ОБЯЗАТЕЛЬНО переведи на русский язык title, intro и все headline/body, сохранив только оригинальные имена собственные и технические обозначения. "
            "Не оставляй английские предложения или английские заголовки. "
            "Главное: ровно 5 items в исходном порядке, каждый item содержит только headline и body, "
            "каждый блок опирается только на свою карточку, 3–6 предложений в body, 2–3 предложения в intro. "
            "Не добавляй card_index, source и url. "
            f"Ошибка проверки: {first_error}\n\nЧЕРНОВИК:\n"
            + json.dumps(draft if 'draft' in locals() else {"raw": draft_content[:6000]}, ensure_ascii=False, indent=2)
            + "\n\nКАРТОЧКИ:\n"
            + json.dumps(top5, ensure_ascii=False, indent=2)
        )
        repaired_content = _request_gemini(repair_prompt, key, model)
        repaired = _normalize_article(_parse_json(repaired_content))
        validate_article(repaired, top5)
        repaired_public = _attach_sources(repaired, top5)
        validate_russian_article(repaired_public)
        return repaired_public
