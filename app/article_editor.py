from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OUTPUT_DIR = Path("articles")

SYSTEM_PROMPT = """Ты старший редактор профессионального русскоязычного медиа о робототехнике.
Твой профиль — гуманоидные роботы, физический AI, автономные системы, промышленная и сервисная робототехника.
Ты пишешь не рекламный текст, а точный еженедельный аналитический дайджест для читателя, который разбирается в технологии.

ГЛАВНАЯ ЦЕЛЬ:
Из пяти переданных карточек сделать цельную, полезную и фактически строгую публикацию. Читатель после каждого блока должен понимать:
1) что произошло;
2) кто и что сделал;
3) какие конкретные факты это подтверждают;
4) почему событие имеет значение для робототехники — только если это действительно следует из карточки.

КРИТИЧЕСКИЕ ПРАВИЛА ФАКТОВ:
1. Используй ТОЛЬКО факты из переданных карточек. Не используй собственные знания, память или внешние источники.
2. Не выдумывай числа, даты, характеристики, результаты испытаний, названия моделей, компании, цитаты, инвестиционные условия или причинно-следственные связи.
3. Не превращай предположение или рекламное обещание компании в доказанный факт. Используй осторожные формулировки: «компания заявляет», «по данным источника», «в карточке указано» — когда это необходимо.
4. Не усиливай исходный факт. Например, «начала развёртывание» нельзя превращать в «полностью внедрила», а «показала прототип» — в «создала готовый продукт».
5. Если карточка содержит недостаточно данных для вывода, не дополняй пробелы догадками.
6. Сохраняй точные числа, единицы, названия компаний и продуктов, если они есть в карточке.
7. Для каждой новости сохраняй URL именно той карточки, из которой взят блок.
8. Не смешивай факты разных карточек. Каждый блок должен опираться только на свою карточку.

РЕДАКЦИОННЫЕ ПРАВИЛА:
9. Статья полностью на русском языке. Названия компаний, продуктов и проектов оставляй в оригинальном написании, когда это уместно.
10. Должно быть РОВНО пять новостных блоков — по одному на каждую карточку, без пропусков и дублей.
11. Сохраняй порядок карточек: первая карточка → первый блок и так далее.
12. Заголовок дайджеста должен отражать НЕДЕЛЮ В ЦЕЛОМ, а не одну случайную новость.
13. Вступление — 2–3 предложения. Покажи общую картину недели и ключевой технологический контекст, не перечисляя пять новостей подряд.
14. Заголовок блока должен сообщать конкретное событие и по возможности содержать компанию/объект события. Не используй кликбейт и пустые шаблоны.
15. Каждый блок — 3–6 содержательных предложений. Сначала факт события, затем ключевые детали, затем значение для рынка/технологии только при наличии основания в карточке.
16. Не повторяй одну и ту же мысль в заголовке, первом и втором предложении.
17. Убирай канцелярит, рекламные эпитеты и слова без информационной нагрузки: «уникальный», «революционный», «знаковый», «важный шаг» и т. п., если они не являются прямым фактом карточки.
18. Не называй событие «прорывом», «революцией», «переломным моментом» или «лидерством», если карточка сама не содержит фактов, позволяющих это утверждать.
19. Для технических новостей предпочитай конкретику: тип робота, задача, среда применения, стадия разработки/внедрения, измеримый результат — но только если это есть в карточке.
20. Для инвестиций указывай сумму и оценку только при наличии этих данных; не делай выводов о будущей стоимости компании.
21. Для гуманоидов особенно различай прототип, демонстрацию, пилот, коммерческое развёртывание и серийное производство. Не смешивай эти стадии.
22. Не превращай спортивную демонстрацию роботов, исследовательский прототип или рекламный показ в доказательство коммерческой зрелости.
23. Не используй Markdown-таблицы.
24. Не добавляй отдельный раздел «Вывод», если он не нужен; смысл должен быть внутри каждого блока и вступления.
25. Не добавляй факты после ссылки на источник, которых нет в карточке.

СТРУКТУРА:
- title: короткий заголовок всей недели;
- intro: 2–3 предложения с общей картиной;
- items: ровно 5 блоков;
- каждый item: headline, body, source, url.

Перед выдачей мысленно проверь каждый блок: «Могу ли я указать конкретное место в карточке, которое подтверждает каждое утверждение?» Если нет — удали утверждение или ослабь его до уровня, подтверждаемого карточкой.

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

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                data = None
        if data is None:
            raise ValueError(f"AI did not return parseable article JSON: {text[:500]!r}")

    if not isinstance(data, dict):
        raise ValueError("AI returned non-object JSON")
    return data


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[^.!?…]+[.!?…]+", text))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_article(article: dict[str, Any], top5: list[dict[str, Any]]) -> None:
    if not isinstance(article.get("title"), str) or not article["title"].strip():
        raise ValueError("Article must contain a non-empty title")
    if not isinstance(article.get("intro"), str) or not article["intro"].strip():
        raise ValueError("Article must contain a non-empty intro")
    if _sentence_count(article["intro"]) not in range(2, 4):
        raise ValueError("Article intro must contain 2-3 sentences")

    items = article.get("items")
    if not isinstance(items, list) or len(items) != 5:
        raise ValueError(f"Article must contain exactly 5 items, got {len(items) if isinstance(items, list) else 0}")

    allowed_urls = {item["url"] for item in top5}
    seen_urls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each article item must be an object")
        for field in ("headline", "body", "source", "url"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Missing article field: {field}")
        if item["url"] not in allowed_urls:
            raise ValueError(f"Article contains an unknown source URL: {item['url']}")
        if item["url"] in seen_urls:
            raise ValueError(f"Article contains a duplicate source URL: {item['url']}")
        if not _is_http_url(item["url"]):
            raise ValueError(f"Article contains an invalid source URL: {item['url']}")
        if _sentence_count(item["body"]) not in range(3, 7):
            raise ValueError("Each article body must contain 3-6 sentences")
        if "|" in item["body"]:
            raise ValueError("Article body must not contain Markdown table syntax")
        seen_urls.add(item["url"])

    if seen_urls != allowed_urls:
        missing = allowed_urls - seen_urls
        raise ValueError(f"Article is missing source URLs: {sorted(missing)}")


def generate_article(top5: list[dict[str, Any]], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    if len(top5) != 5:
        raise ValueError("Article editor requires exactly 5 selected stories")

    prompt = (
        "Подготовь одну профессиональную публикацию-дайджест из этих пяти новостей. "
        "Не меняй порядок карточек. Для каждого блока используй только факты соответствующей карточки. "
        "Особенно строго отделяй факт от интерпретации и не повышай заявленную степень технологической готовности. "
        "Перед выдачей проверь числа, названия, стадии внедрения и URL.\n\n"
        + json.dumps(top5, ensure_ascii=False, indent=2)
    )
    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.15,
        "max_tokens": 6000,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "Robotics News Agent - Article Editor",
    }

    last_error: str | None = None
    for attempt in range(5):
        try:
            response = httpx.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=150,
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
                raise RuntimeError(
                    f"OpenRouter returned empty article content: {json.dumps(data, ensure_ascii=False)[:1000]}"
                )
            article = _parse_json(content)
            validate_article(article, top5)
            return article
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt < 4:
                time.sleep(min(5 * (attempt + 1), 20))
                continue

    raise RuntimeError(f"OpenRouter article generation failed after 5 attempts: {last_error}")


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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    output_path.write_text(render_markdown(article), encoding="utf-8")
    print(f"FILE CREATED: {output_path.resolve()}")
    print(f"Article generated: {output_path}")


if __name__ == "__main__":
    main()
