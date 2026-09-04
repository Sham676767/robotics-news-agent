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

from app.fact_guard import validate_factual_grounding
from app.language_guard import validate_russian_article

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_FALLBACK_MODELS = []
OUTPUT_DIR = Path("articles")
MAX_ARTICLE_REPAIR_ATTEMPTS = 3
_GENERIC_HEADLINES = {
    "новость",
    "новость дня",
    "главное",
    "главная новость",
    "событие",
    "событие дня",
}

SYSTEM_PROMPT = """Ты старший редактор профессионального русскоязычного медиа о робототехнике.
Твой профиль — гуманоидные роботы, физический AI, автономные системы, промышленная и сервисная робототехника.
Ты пишешь не рекламный текст, а точный ежедневный аналитический дайджест для читателя, который разбирается в технологии.

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
5. Если карточка содержит недостаточно данных для вывода, не дополняй пробелы догадками. Не добавляй распространённые объяснения технологии («без традиционного программирования», «система управления», «коммерческая зрелость» и т. п.), если этого нет в карточке.
6. Сохраняй точные числа, единицы, названия компаний и продуктов, если они есть в карточке.
7. Никогда не придумывай и не копируй URL вручную. Источник и URL будут добавлены программой по порядку карточек.
8. Не смешивай факты разных карточек. Каждый блок должен опираться только на свою карточку.

РЕДАКЦИОННЫЕ ПРАВИЛА:
9. Статья полностью на русском языке. Названия компаний, продуктов и проектов оставляй в оригинальном написании, когда это уместно. Английские фразы и предложения не используй.
10. Должно быть РОВНО пять новостных блоков — по одному на каждую карточку, без пропусков и дублей.
11. Сохраняй порядок карточек: первая карточка → первый блок и так далее.
12. Заголовок дайджеста должен отражать ДЕНЬ В ЦЕЛОМ, а не одну случайную новость. Он не должен содержать чисел, оценок или обобщений, которых нет в карточках.
13. Вступление — 2–3 предложения. Покажи общую картину ДНЯ и ключевой технологический контекст, не перечисляя пять новостей подряд. Не смешивай в одном предложении факты разных карточек и не делай общий вывод, если карточки его не подтверждают. Все предложения должны быть на русском языке.
14. Заголовок блока должен сообщать конкретное событие и по возможности содержать компанию/объект события. Не используй кликбейт, шаблоны «Новость», «Главное» или «Событие дня». Заголовок должен быть на русском, кроме оригинальных названий компаний, продуктов и проектов; все пять заголовков должны отличаться друг от друга.
15. Каждый блок — 3–6 содержательных предложений. Сначала факт события, затем ключевые детали, затем значение для рынка/технологии только при наличии основания в карточке.
16. Не повторяй одну и ту же мысль в заголовке, первом и втором предложении. Не упоминай «карточки», TOP-5 или внутренний процесс подготовки текста.
17. Убирай канцелярит, рекламные эпитеты и слова без информационной нагрузки: «уникальный», «революционный», «знаковый», «важный шаг» и т. п., если они не являются прямым фактом карточки.
18. Не называй событие «прорывом», «революцией», «переломным моментом» или «лидерством», если карточка сама не содержит фактов, позволяющих это утверждать.
19. Для технических новостей предпочитай конкретику: тип робота, задача, среда применения, стадия разработки/внедрения, измеримый результат — но только если это есть в карточке.
20. Для инвестиций указывай сумму и оценку только при наличии этих данных; не делай выводов о будущей стоимости компании.
21. Для гуманоидов особенно различай прототип, демонстрацию, пилот, коммерческое развёртывание и серийное производство. Не смешивай эти стадии.
22. Не превращай спортивную демонстрацию роботов, исследовательский прототип или рекламный показ в доказательство коммерческой зрелости.
23. Не используй Markdown-таблицы.
24. Не добавляй отдельный раздел «Вывод», если он не нужен; смысл должен быть внутри каждого блока и вступления.
25. Не добавляй факты после ссылки на источник, которых нет в карточке.
26. Перед возвратом результата отдельно проверь title, intro и каждый headline: они должны быть написаны по-русски; допускаются только оригинальные имена компаний, продуктов, проектов и общепринятые технические обозначения.

ФОРМАТ ВЫВОДА:
Верни ТОЛЬКО один валидный JSON-объект без Markdown-ограждений, YAML, пояснений или текста до/после JSON.
- title: короткий заголовок всего выпуска за день;
- intro: 2–3 предложения с общей картиной;
- items: ровно 5 блоков;
- каждый item содержит ТОЛЬКО headline и body;
- не добавляй card_index, source или url — это служебные поля, их добавит программа по порядку карточек.
"""

ARTICLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "intro", "items"],
    "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string"},
        "items": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["headline", "body"],
                "properties": {
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
    },
}


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
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                data = None
        if data is None:
            raise ValueError(f"AI did not return parseable article JSON: {text[:500]!r}")
    if not isinstance(data, dict):
        raise ValueError("AI returned non-object JSON")
    return data


def _is_parseable_article_json(content: Any) -> bool:
    """Return whether a provider response contains a JSON object for the article."""
    if not isinstance(content, str) or not content.strip():
        return False
    try:
        _parse_json(content)
    except ValueError:
        return False
    return True


def _normalize_article(article: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(article)
    items = article.get("items")
    if isinstance(items, list) and len(items) == 5:
        normalized["items"] = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                normalized["items"].append({**item, "card_index": index})
            else:
                normalized["items"].append(item)
    return normalized


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[^.!?…]+[.!?…]+", text))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _headline_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip(" .,!?:;—–-")


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

    actual_indexes: list[int] = []
    headline_keys: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each article item must be an object")
        for field in ("headline", "body", "card_index"):
            if field not in item:
                raise ValueError(f"Missing article field: {field}")
        if not isinstance(item["headline"], str) or not item["headline"].strip():
            raise ValueError("Each article headline must be a non-empty string")
        headline_key = _headline_key(item["headline"])
        if headline_key in _GENERIC_HEADLINES:
            raise ValueError("Article headline must describe a concrete event")
        headline_keys.append(headline_key)
        if not isinstance(item["body"], str) or not item["body"].strip():
            raise ValueError("Each article body must be a non-empty string")
        if not isinstance(item["card_index"], int) or isinstance(item["card_index"], bool):
            raise ValueError("Each article card_index must be an integer")
        actual_indexes.append(item["card_index"])
        if _sentence_count(item["body"]) not in range(3, 7):
            raise ValueError("Each article body must contain 3-6 sentences")
        if "|" in item["body"]:
            raise ValueError("Article body must not contain Markdown table syntax")

    if actual_indexes != [1, 2, 3, 4, 5]:
        raise ValueError(f"Article card_index sequence must be exactly [1, 2, 3, 4, 5], got {actual_indexes}")
    if len(headline_keys) != len(set(headline_keys)):
        raise ValueError("Article headlines must not repeat")

    for card in top5:
        url = card.get("url")
        if not isinstance(url, str) or not _is_http_url(url):
            raise ValueError(f"Selected story contains an invalid source URL: {url!r}")


def _attach_sources(article: dict[str, Any], top5: list[dict[str, Any]]) -> dict[str, Any]:
    result = {"title": article["title"], "intro": article["intro"], "items": []}
    for item in article["items"]:
        card = top5[item["card_index"] - 1]
        public_item = {
            "headline": item["headline"],
            "body": item["body"],
            "source": str(card.get("source") or card.get("publisher") or "Источник"),
            "url": card["url"],
        }
        image_url = card.get("image_url")
        if isinstance(image_url, str) and _is_http_url(image_url):
            public_item["image_url"] = image_url
        result["items"].append(public_item)
    return result


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 60.0))
        except ValueError:
            pass
    base = float(os.getenv("OPENROUTER_RETRY_BASE_SECONDS", "2"))
    maximum = float(os.getenv("OPENROUTER_RETRY_MAX_SECONDS", "20"))
    return min(maximum, base * (2**attempt))


def _request_openrouter(payload: dict[str, Any], headers: dict[str, str], timeout: float = 120) -> str:
    max_attempts = max(1, int(os.getenv("OPENROUTER_MAX_ATTEMPTS", "3")))
    retryable_statuses = {408, 409, 429, 500, 502, 503, 504}
    last_error: str | None = None
    for attempt in range(max_attempts):
        try:
            response = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
            if response.status_code in retryable_statuses:
                last_error = f"HTTP {response.status_code}: {response.text[:1000]}"
                if attempt + 1 < max_attempts:
                    delay = _retry_delay(response, attempt)
                    print(f"⚠️ OpenRouter transient HTTP {response.status_code}; retry {attempt + 2}/{max_attempts} in {delay:.1f}s")
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            content = (choices[0].get("message") or {}).get("content") if choices else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(f"OpenRouter returned empty article content: {json.dumps(data, ensure_ascii=False)[:1000]}")
            used_model = data.get("model")
            if used_model:
                print(f"✅ OpenRouter article response model: {used_model}")
            return content
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            last_error = str(exc)
            if attempt + 1 < max_attempts:
                delay = float(os.getenv("OPENROUTER_RETRY_BASE_SECONDS", "2")) * (2**attempt)
                print(f"⚠️ OpenRouter request error; retry {attempt + 2}/{max_attempts} in {delay:.1f}s: {last_error}")
                time.sleep(min(delay, float(os.getenv("OPENROUTER_RETRY_MAX_SECONDS", "20"))))
                continue
    raise RuntimeError(f"OpenRouter request failed after {max_attempts} attempts: {last_error}")


def _fallback_models(primary_model: str) -> list[str]:
    configured = [value.strip() for value in os.getenv("OPENROUTER_FALLBACK_MODELS", "").split(",") if value.strip()]
    return list(dict.fromkeys([primary_model, *configured, *DEFAULT_FALLBACK_MODELS]))


def _payload(messages: list[dict[str, str]], model: str, models: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": 5000,
        # This task needs a compact JSON payload, not an exposed reasoning trace.
        # Disabling reasoning prevents it from consuming the entire output budget.
        "reasoning": {"effort": "none"},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "robotics_daily_digest", "strict": True, "schema": ARTICLE_SCHEMA},
        },
    }
    if len(models) > 1:
        payload["models"] = models
        payload["route"] = "fallback"
    return payload


def generate_article(top5: list[dict[str, Any]], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    if len(top5) != 5:
        raise ValueError("Article editor requires exactly 5 selected stories")

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    models = _fallback_models(model)
    print(f"🤖 OpenRouter model chain: {' → '.join(models)}")
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
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "Robotics News Agent - Article Editor",
    }
    current_content = _request_openrouter(_payload(messages, model, models), headers)

    last_error: Exception | None = None

    # A valid JSON response can still miss an editorial constraint. Give it two
    # bounded correction attempts before safely failing.
    for repair_attempt in range(MAX_ARTICLE_REPAIR_ATTEMPTS + 1):
        try:
            draft = _normalize_article(_parse_json(current_content))
            validate_article(draft, top5)
            validate_factual_grounding(draft, top5)
            public_article = _attach_sources(draft, top5)
            validate_russian_article(public_article)
            return public_article
        except (ValueError, RuntimeError) as validation_error:
            last_error = validation_error
            if repair_attempt >= MAX_ARTICLE_REPAIR_ATTEMPTS:
                break

            try:
                repair_input = _normalize_article(_parse_json(current_content))
            except ValueError:
                repair_input = {"raw": current_content[:6000]}

            repair_scope = (
                "Пересобери все поля черновика заново, соблюдая ограничение длины каждого блока. "
                if "Each article body must contain" in str(validation_error)
                else "Исправь ТОЛЬКО ошибки в черновике статьи ниже. Не переписывай удачные части без необходимости. "
            )
            repair_prompt = (
                repair_scope
                + "ОБЯЗАТЕЛЬНО переведи на русский язык title, intro и все headline/body, сохранив только оригинальные имена собственные и технические обозначения. "
                "Не оставляй английские предложения или английские заголовки. "
                "Это ЕЖЕДНЕВНЫЙ выпуск: не используй слова «неделя», «недели», «недельный» или «еженедельный» в title и intro. "
                "Главное: верни ТОЛЬКО валидный JSON-объект без Markdown, YAML или пояснений. "
                "В нём должно быть ровно 5 items в исходном порядке, каждый item содержит только headline и body, "
                "каждый блок опирается только на свою карточку, body содержит РОВНО три простых предложения, "
                "и КАЖДОЕ из них заканчивается точкой. Не используй списки, переносы строк или маркированные пункты в body. "
                "В intro должно быть 2–3 предложения. Не добавляй card_index, source и url. "
                f"Ошибка проверки: {validation_error}\n\n"
                "ЧЕРНОВИК:\n"
                + json.dumps(repair_input, ensure_ascii=False, indent=2)
                + "\n\nКАРТОЧКИ:\n"
                + json.dumps(top5, ensure_ascii=False, indent=2)
            )
            repair_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ]
            current_content = _request_openrouter(
                _payload(repair_messages, model, models), headers
            )

    raise RuntimeError(
        f"Article remained invalid after {MAX_ARTICLE_REPAIR_ATTEMPTS} repair attempts: {last_error}"
    )


def render_markdown(article: dict[str, Any]) -> str:
    lines = [f"# {article['title']}", "", article["intro"], ""]
    for index, item in enumerate(article["items"], start=1):
        lines.extend([
            f"## {index}. {item['headline']}",
            "",
        ])
        image_url = item.get("image_url")
        if isinstance(image_url, str) and _is_http_url(image_url):
            lines.extend([f"![{item['headline']}](<{image_url}>)", ""])
        lines.extend([
            item["body"],
            "",
            f"Источник: [{item['source']}]({item['url']})",
            "",
        ])
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
