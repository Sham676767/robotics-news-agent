import socket
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.legal_draft import load_legal_draft
from app.config import Settings
from app.reel_script import DISCLAIMER, topic_sources
from app.topics import Article, PrimaryReference, Topic


@pytest.fixture(autouse=True)
def block_external_apis(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External API calls must be mocked in tests")

    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def legal_package():
    return load_legal_draft(Path(__file__).parent / "fixtures" / "legal_draft.json")


# Synthetic script fixtures: no actual legal rules or recommendations.
@pytest.fixture
def script_topic():
    return Topic("fixture-topic", "Учебная проверка договора", (
        Article("fixture", "Учебный источник", "media", "https://media.example/fixture",
                "Учебная проверка договора", "Синтетический материал без норм права: проверка договора, "
                "документы, переписка, консультация и вопросы специалисту.",
                datetime(2026, 10, 22, tzinfo=timezone.utc)),
    ), (PrimaryReference("document", "Учебный документ без норм права",
                         "https://law.example/document/fixture", "Учебный материал для тестов.", True),))


@pytest.fixture
def script_data(script_topic):
    hook = "Подписываете договор? Проверьте детали."
    essence = (
        "В договоре легко пропустить условие, которое позже станет причиной разногласий. "
        "Этот учебный пример показывает, как подготовиться к обсуждению документа со специалистом. "
        "Обратите внимание на описание обязательств, порядок общения сторон и документы, которые "
        "помогают восстановить ход событий. Отдельная фраза не заменяет чтение полного текста."
    )
    actions = (
        "Соберите договор, приложения и переписку в одном месте. Выпишите непонятные формулировки "
        "и вопросы, которые хотите задать. Сравните собственные ожидания с тем, что написано "
        "в документе. Если ситуация вызывает сомнения, обсудите её с юристом, предоставив исходные "
        "материалы. Так разговор будет предметным и понятным."
    )
    return {
        "hook": hook, "voiceover": "\n\n".join([hook, essence, actions, Settings().script_cta]),
        "on_screen_text": ["Соберите документы", "Подготовьте вопросы"],
        "caption": "Учебный пример подготовки вопросов по договору.",
        "hashtags": ["#договор", "#юридическаяПомощь"],
        "sources": [asdict(source) for source in topic_sources(script_topic)], "disclaimer": DISCLAIMER,
    }
