from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OUTPUT_PATH = Path("data/article_draft.md")

SYSTEM_PROMPT = """Ты профессиональный русскоязычный редактор новостей о робототехнике.
Пиши живо и понятно, но без кликбейта.
КРИТИЧЕСКИЕ ПРАВИЛА:
1. Используй только факты, присутствующие в переданных карточках новостей.
2. Не выдумывай числа, даты, характеристики, цитаты, компании или события.
3. Не копируй формулировки источника дословно; пересказывай своими словами.
4. Не добавляй информацию из собственной памяти.
5. Сохраняй URL каждого первоисточника.
6. Статья должна быть на русском языке.
7. Ровно пять новостей, в порядке важности.
8. Заголовок должен отражать содержание всей подборки, а не одну новость.
9. Не используй Markdown-таблицы.

Верни ТОЛЬКО JSON следующего вида:
{"title":"...","intro":"...","items":[{"headline":"...","body":"...","source":"...","url":"..."},{"headline":"...","body":"...","source":"...","url":"..."},{"headline":"...","body":"...","source":"...","url":"..."},{"headline":"...","body":"...","source":"...","url":"..."},{"headline":"...","body":"...","source":"...","url":"..."}]}
"""


def _parse_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("AI returned non-object JSON")
    return data


def validate_article(article: dict[str, Any], top5: list[dict[str, Any]]) -> None:
    if not article.get("title") or not article.get("intro"):
        raise ValueError("Article must contain title and intro")
    items = article.get("items")
    if not isinstance(items, list) or len(items) != 5:
        raise ValueError(f"Article must contain exactly 5 items, got {len(items) if isinstance(items, list) else 0}")

    allowed_urls = {item["url"] for item in top5}
    seen_urls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each article item must be an object")
        for field in ("headline", "body", "source", "url"):
            if not item.get(field):
                raise ValueError(f"Missing article field: {field}")
        if item["url"] not in allowed_urls:
            raise ValueError(f"Article contains an unknown source URL: {item['url']}")
        if item["url"] in seen_urls:
            raise ValueError("Duplicate source URL in article")
        seen_urls.add(item["url"])


def generate_article(top5: list[dict[str, Any]], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    if len(top5) != 5:
        raise ValueError("Article editor requires exactly 5 selected stories")

    prompt = (
        "Подготовь одну публикацию-дайджест из этих пяти новостей. "
        "Каждая карточка является единственным источником фактов для соответствующего блока.\n\n"
        + json.dumps(top5, ensure_ascii=False, indent=2)
    )
    response = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "Robotics News Agent — Article Editor",
        },
        json={
            "model": os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 5000,
        },
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {json.dumps(data, ensure_ascii=False)[:1000]}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError(f"OpenRouter returned empty article content: {json.dumps(data, ensure_ascii=False)[:1000]}")

    article = _parse_json(content)
    validate_article(article, top5)
    return article


def render_markdown(article: dict[str, Any]) -> str:
    lines = [f"# {article['title']}", "", article["intro"], ""]
    for index, item in enumerate(article["items"], start=1):
        lines.extend(
            [
                f"## {index}. {item['headline']}",
                "",
                item["body"],
                "",
                f"Источник: [{item['source']}]({item['url']})",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    top5_path = Path("data/latest_top5.json")
    top5 = json.loads(top5_path.read_text(encoding="utf-8"))
    article = generate_article(top5)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_markdown(article), encoding="utf-8")
    print(f"Article generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
