"""Explicitly non-publishable local fixture, never a source of real legal claims."""
from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import asdict
from datetime import datetime, timezone

from app.config import Settings
from app.reel_script import DISCLAIMER, ReelScript, parse_script, topic_sources
from app.script_review import ClaimCheck, ScriptReview, digest, review_claims
from app.topics import Article, PrimaryReference, Topic, topic_to_dict
from app.tts import SynthesizedSpeech

HOOK = "Это технический тест видеоролика."
ESSENCE = ("Здесь демонстрируется оформление будущего видео, а не объясняются нормы права. "
           "Тестовый текст помогает проверить размер букв, переносы строк и расположение элементов "
           "на вертикальном экране. Указанные реквизиты вымышлены и используются только для проверки "
           "программы. Они не относятся к реальным законам и не должны применяться в жизни.")
ACTIONS = ("Посмотрите на центральные титры и нижнюю плашку. Проверьте, удобно ли читать текст "
           "на телефоне и виден ли дисклеймер. На финальном экране можно разместить название "
           "услуги и контакт. Вместо человеческого голоса звучит тихий тестовый тон. Настоящая "
           "озвучка подключается в обычном режиме после проверки сценария по первоисточнику.")
NORM = "Вымышленные реквизиты технической фикстуры: ч. 2 ст. 999 99999-ФЗ. Это не реальная норма."


def stub_script(settings: Settings) -> tuple[Topic, ReelScript, ScriptReview]:
    primary = "https://fixture.example/test-norm"
    caption = "Техническая демонстрация с вымышленными реквизитами, без юридических рекомендаций."
    screens = ["Технический тест", "Реквизиты вымышлены"]
    content = "\n".join((NORM, HOOK, ESSENCE, ACTIONS, caption, *screens))
    topic = Topic("stub-topic", "Технический тест без реальных норм", (
        Article("stub", "Локальная фикстура", "media", "https://fixture.example/test", "Технический тест",
                content, datetime.now(timezone.utc)),),
        (PrimaryReference("document", "Техническая фикстура", primary, NORM, True, content),))
    raw = {"hook": HOOK, "voiceover": "\n\n".join((HOOK, ESSENCE, ACTIONS, settings.script_cta)),
           "on_screen_text": screens, "caption": caption, "hashtags": ["#тест"],
           "sources": [asdict(item) for item in topic_sources(topic)], "disclaimer": DISCLAIMER}
    script = parse_script(raw, topic, settings)
    checks = []
    for claim in review_claims(script, settings):
        non_factual = claim.field == "hashtags" or claim.text.rstrip(".!?…") == settings.script_cta.rstrip(".!?…")
        checks.append(ClaimCheck(claim.id, "non_factual" if non_factual else "supported",
                                "" if non_factual else primary,
                                "" if non_factual else (NORM if claim.field.startswith("sources[") else claim.text),
                                "Локальная тестовая фикстура, не правовая проверка.", claim.text, claim.field))
    review = ScriptReview(digest(script.to_dict()), digest(topic_to_dict(topic)), "local-stub", (), tuple(checks),
                          "Техническая фикстура. Публикация запрещена.")
    return topic, script, review


class ToneProvider:
    def synthesize(self, text: str) -> SynthesizedSpeech:
        buffer = io.BytesIO()
        rate, seconds = 24000, 30
        with wave.open(buffer, "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            samples = bytearray()
            for index in range(rate * seconds):
                fade = min(1.0, index / 1200, (rate * seconds - index) / 1200)
                samples.extend(struct.pack("<h", round(900 * fade * math.sin(2 * math.pi * 440 * index / rate))))
            output.writeframes(samples)
        return SynthesizedSpeech(buffer.getvalue(), "local-stub", "tone-440hz", "local-tone",
                                 timing_note="Local tone has no speech; estimated timings are for layout testing only")
