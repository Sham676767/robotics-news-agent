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

FIXTURE_HOOK = "Подписываете договор? Проверьте детали."
FIXTURE_ESSENCE = (
    "В договоре легко пропустить условие, которое позже станет причиной разногласий. "
    "Этот учебный пример показывает, как подготовиться к обсуждению документа со специалистом. "
    "Обратите внимание на описание обязательств, порядок общения сторон и документы, которые "
    "помогают восстановить ход событий. Отдельная фраза не заменяет чтение полного текста."
)
FIXTURE_ACTIONS = (
    "Соберите договор, приложения и переписку в одном месте. Выпишите непонятные формулировки "
    "и вопросы, которые хотите задать. Сравните собственные ожидания с тем, что написано "
    "в документе. Если ситуация вызывает сомнения, обсудите её с юристом, предоставив исходные "
    "материалы. Так разговор будет предметным и понятным."
)
FIXTURE_NORM = "Синтетический реквизит для теста, не реальная норма: ч. 2 ст. 999 99999-ФЗ."


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
                         "https://law.example/document/fixture", "Учебный материал для тестов.", True,
                         "\n".join([FIXTURE_NORM, FIXTURE_HOOK, FIXTURE_ESSENCE, FIXTURE_ACTIONS,
                                    "Соберите документы", "Подготовьте вопросы",
                                    "Учебный пример подготовки вопросов по договору."])),))


@pytest.fixture
def script_data(script_topic):
    return {
        "hook": FIXTURE_HOOK,
        "voiceover": "\n\n".join([FIXTURE_HOOK, FIXTURE_ESSENCE, FIXTURE_ACTIONS, Settings().script_cta]),
        "on_screen_text": ["Соберите документы", "Подготовьте вопросы"],
        "caption": "Учебный пример подготовки вопросов по договору.",
        "hashtags": ["#договор", "#юридическаяПомощь"],
        "sources": [asdict(source) for source in topic_sources(script_topic)], "disclaimer": DISCLAIMER,
    }


@pytest.fixture
def review_payload():
    from app.script_review import review_claims

    def build(script, topic, settings):
        primary = topic.references[0]
        checks = []
        for claim in review_claims(script, settings):
            non_factual = claim.field == "hashtags" or claim.text.rstrip(".!?…") == settings.script_cta.rstrip(".!?…")
            checks.append({"id": claim.id, "verdict": "non_factual" if non_factual else "supported",
                           "source_url": "" if non_factual else primary.url,
                           "quote": "" if non_factual else (FIXTURE_NORM if claim.field.startswith("sources[") else claim.text),
                           "reason": "Призыв или теги." if non_factual else "Подтверждено синтетическим материалом."})
        return {"summary": "Учебная сверка завершена.", "claims": checks}
    return build


@pytest.fixture
def tts_settings(tmp_path):
    return Settings(elevenlabs_api_key="eleven-test-key", elevenlabs_voice_id="fixture-voice",
                    elevenlabs_model_id="fixture-model", tts_timeout=5,
                    tts_retry_base_seconds=0, tts_retry_max_seconds=0,
                    tts_output_dir=tmp_path / "audio")


@pytest.fixture
def wav_bytes():
    import io
    import wave
    def build(duration=1.0, rate=24000):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(rate)
            file.writeframes(b"\0\0" * round(duration * rate))
        return buffer.getvalue()
    return build
