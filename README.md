# Legal Reels Agent

Генератор коротких вертикальных видео о праве РФ для предпринимателей и людей,
которым может понадобиться юридическая помощь. Пайплайн собирает темы из
RSS/HTML, объединяет повторы, выбирает тему, генерирует и проверяет сценарий,
озвучивает его через ElevenLabs и собирает MP4 через FFmpeg.

Целевой формат — Instagram Reels, 9:16, 30–60 секунд; технический предел
готового видео — 90 секунд, 1080×1920, H.264/AAC. Публикация через Graph API
выполняется отдельной командой после ручного одобрения.

## Установка

### Docker — рекомендуемый запуск

Нужны Git, Docker Desktop либо Docker Engine с Compose. Образ содержит
Python 3.11, FFmpeg/ffprobe, libass и шрифт с кириллицей.

```bash
git clone https://github.com/Sham676767/robotics-news-agent.git
cd robotics-news-agent
# Пока этапы находятся в отдельных PR, выберите ветку нужного PR.
# Полный пайплайн и итоговый аудит включены в codex/pipeline-audit.
git switch codex/pipeline-audit
# Только при первой настройке. Существующий .env не заменяйте:
cp .env.example .env
docker compose build
docker compose run --rm agent python -m app --help
```

Команды выполняются из корня репозитория. Compose подключает папки
`drafts`, `data`, `audio`, `renders`, `templates` и `backgrounds`.
Первичная сборка и установка зависимостей требуют интернета.

### Локальное виртуальное окружение

Нужен Python 3.11+. Для рендера дополнительно установите FFmpeg с libx264,
AAC и libass, Fontconfig (`fc-match`) и шрифт `DejaVu Sans`. Их наличие
проверяет dry-run. Если локальные зависимости неудобно устанавливать,
используйте Docker.

```bash
python3 -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# Если .env ещё отсутствует:
cp .env.example .env
python -m app --help
```

`python main.py` — равнозначная точка входа. Без аргументов CLI проверяет
настройки основы проекта; полную готовность проверяет `run-all --dry-run`.

## Ключи и настройки

CLI читает `.env` из текущей папки. Переменные окружения имеют приоритет.
Все параметры и значения по умолчанию перечислены в [.env.example](.env.example).
Секреты записывайте в этот локальный файл, а не в команды, код или черновики.
`.env` исключён из Git и Docker-образа. Не отправляйте его в PR.

| Сервис | Что заполнить в `.env` |
| --- | --- |
| OpenRouter | `OPENROUTER_API_KEY` из своего кабинета, `OPENROUTER_MODEL` — доступная вашему аккаунту модель со структурированным JSON |
| ElevenLabs | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` своего выбранного голоса; `TTS_PROVIDER=elevenlabs` |
| Instagram | `INSTAGRAM_LOGIN`, `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_API_VERSION` — см. следующий раздел |
| S3 | `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` своего провайдера |

Дополнительно:

- `PIPELINE_MODE=live` — обычный запуск; `stub` — локальные заглушки.
- `OPENROUTER_FALLBACK_MODELS` — необязательные запасные модели через запятую.
- `SCRIPT_CTA` — финальная фраза; по умолчанию «Сохраните ролик и поделитесь им».
- `DRAFTS_DIR`, `TTS_OUTPUT_DIR`, `RENDER_OUTPUT_DIR` — папки результатов.
- `S3_PUBLIC_BASE_URL` — корень прямых публичных ссылок. Если пусто, используется
  временная подписанная ссылка, бакет может оставаться приватным.
- `S3_PRESIGN_TTL_SECONDS=7200` — срок временной ссылки;
  `S3_DELETE_AFTER_PUBLISH=true` — удалить объект после успешной публикации.

Создайте бакет заранее. Ключам S3 нужны запись, чтение и, при включённой
очистке, удаление объектов. URL для Instagram должен вести прямо на MP4
через доступный из интернета HTTPS на порту 443. Локальный MinIO предназначен
для проверки хранилища. Подробности: [docs/instagram.md](docs/instagram.md).

Настройки тем — в `sources.yaml`: по умолчанию свежесть **30 дней**, аудитория —
бизнес и потенциальные клиенты юридических услуг. В `templates/default.yaml`
задайте `service_name` и `contact` для финального экрана, при желании измените
оформление. Пустые контакты допустимы; финал покажет CTA и дисклеймер.

## Настройка Instagram

1. Используйте профессиональный аккаунт **Business или Creator**.
2. В [Meta for Developers](https://developers.facebook.com/apps/) создайте
   приложение и настройте Instagram API с **Instagram Login**. Подключите
   нужный аккаунт и выполните требования панели Meta к тестовым ролям и доступу.
3. Получите токен для этого аккаунта с разрешениями
   `instagram_business_basic` и `instagram_business_content_publish`.
   Выдача токена/OAuth выполняется через Meta, вне этой CLI.
4. Запишите в `.env`: `INSTAGRAM_LOGIN=instagram`, числовой
   `INSTAGRAM_USER_ID` (не имя профиля), `INSTAGRAM_ACCESS_TOKEN` и
   `INSTAGRAM_API_VERSION` в формате `vNN.N`. Версию возьмите из поддерживаемых
   вашим приложением Meta; обозначение `vNN.N` нужно заменить реальным значением.
5. Проверьте срок действия токена и настройте его обновление в своей процедуре
   эксплуатации: приложение не выполняет OAuth и автоматическое обновление.
   Для аккаунтов за пределами разрешённого тестового доступа выполните требования
   Meta к режиму приложения и проверке разрешений.

Для Instagram Login привязка Facebook Page не требуется. Если у вас уже
настроен Facebook Login, задайте `INSTAGRAM_LOGIN=facebook`, используйте
соответствующий токен и связанный с Facebook Page профессиональный Instagram.
Разрешения этих двух способов различаются — не смешивайте токены и scopes.
См. [официальную коллекцию Meta](https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login)
и [подробности подключения](docs/instagram.md#подключение).

## Проверка без платных запросов

```bash
# Проверка реальных настроек и план будущего запуска:
docker compose run --rm agent python -m app run-all --dry-run --count 1
# Проверка локальных инструментов без ключей:
docker compose run --rm agent python -m app run-all --stub --dry-run
# Настоящий тестовый MP4, без сервисов генерации:
docker compose run --rm agent python -m app run-all --stub
```

`run-all --dry-run` проверяет наличие и формат ключей, источники, шаблон,
FFmpeg/ffprobe, libass, шрифт и доступ к папкам. Показывает модель, голос,
этапы, число роликов и оценку количества платных запросов с ретраями.
**Он не выполняет этапы генерации, сетевые запросы и запись файлов, не меняет
историю тем.** Код выхода: 0 — локальная готовность, 2 — список проблем.
Действительность токена, баланс и доступность облачного URL проверяются отдельно.

`--stub` создаёт полный тестовый черновик: фиксированный учебный текст с явно
вымышленными реквизитами, тихий тон вместо голоса, оценочные тайминги и реальный
MP4. Такой ролик нельзя одобрить или опубликовать. Для воспроизводимого dry-run
с синтетическими настройками предусмотрен тест
`tests/test_pipeline_preflight.py`: реальные ключи не нужны.

## Полный запуск

После настройки ключей обычный `run-all` вызывает платные сервисы:

```bash
docker compose run --rm agent python -m app run-all --count 1
# Просмотрите комплект drafts/reels/reel-ID/ и проверьте первоисточники.
# Замените reel-ID полным ID из результата команды:
docker compose run --rm agent python -m app approve reel-ID
docker compose run --rm agent python -m app publish reel-ID --dry-run
docker compose run --rm agent python -m app publish reel-ID
# После фактического использования темы — отдельное подтверждение:
docker compose run --rm agent python -m app mark-used topic-ID
```

`run-all` заканчивает работу на `awaiting_approval`. `approve` фиксирует
ручное одобрение конкретных материалов и аккаунта; `publish` отдельно загружает
MP4 в S3, создаёт контейнер REELS, ждёт обработки и публикует его.
Проверка `publish --dry-run` требует уже одобренного комплекта.

Комплект включает сценарий, результат сверки с источниками, аудио, тайминги,
видео, титры, подпись, источники и состояние публикации. В нём есть `topic.json`
с ID темы. Изменение материалов после одобрения блокирует публикацию.
При расхождении с первоисточником сценарий попадает в карантин с причиной.
При ошибке сохраняются уже подготовленные материалы и имя этапа.

Сценарий: хук → суть → действия зрителя → CTA, вся озвучка 80–140 слов.
До 6 титров по 60 символов, подпись до 1000 символов, 1–10 хэштегов.
Обязательны конкретная норма и источник, а также дисклеймер
«Не является юридической консультацией». Проверки и LLM-сверка помогают
редактору; применимость нормы к ситуации требует ручной юридической проверки.

Ретраи ограничены и используют экспоненциальную паузу. При потере ответа
публикации повторный `publish` сначала сверяет старый контейнер и не отправляет
второй пост вслепую. Статусы и восстановление: [docs/instagram.md](docs/instagram.md).

## Команды по этапам

Ниже примеры для установленного локального окружения. В Docker добавляйте
`docker compose run --rm agent` перед `python`.

```bash
python -m app collect --count 2 --max-age-days 30
python -m app script --input data/collected_topics.json --topic-id topic-ID
python -m app tts --input drafts/reel-script-ID.json
python -m app render --input drafts/reel-script-ID.json \
  --timings audio/tts-ID/timings.json
# Необязательные локальные фоновые клипы:
python -m app render --input drafts/reel-script-ID.json \
  --timings audio/tts-ID/timings.json --clips-dir backgrounds
# Собрать уже готовые материалы в комплект без повторной генерации:
python -m app prepare --input drafts/reel-script-ID.json \
  --timings audio/tts-ID/timings.json --video renders/render-ID/video.mp4
```

Сбор объединяет одинаковые URL и явные повторы локально, смысловые — через
OpenRouter, сохраняя источники. Использование темы подтверждается только
`mark-used`. Если тем несколько, `script` требует `--topic-id`.
Отдельный локальный редактор текстовых черновиков сохранён как совместимый
инструмент: `python -m app --draft tests/fixtures/legal_draft.json`.
Он не генерирует видео и не выдаёт разрешение на публикацию.

## Тесты и покрытие

```bash
python -m pip install -r requirements-dev.txt
python -m coverage run -m pytest -q
python -m coverage report
python -m coverage html
python -m pyflakes app main.py scripts tests
python -m vulture app main.py scripts --min-confidence 90
python -m pip check
```

HTML-отчёт — `htmlcov/index.html`. `.coveragerc` измеряет строки и ветви
условий всех модулей `app`, минимальное совокупное покрытие — **90%**.
Отчёты исключены из Git и образа. Внешние API в тестах замоканы, сетевые
соединения запрещены общей фикстурой. Тесты реального рендера и dry-run с
настоящими инструментами требуют Docker-окружения:

```bash
docker compose run --rm agent sh -c 'python -m pip install -r requirements-dev.txt && python -m coverage run -m pytest -q && python -m coverage report && python -m pip check'
```

Для сохранения HTML на компьютере используйте локальное окружение либо
дополнительно подключите каталог отчёта к контейнеру. Без FFmpeg локально
соответствующие интеграционные тесты будут пропущены. GitHub Actions остаётся
на паузе: шаблон `.github/workflows/tests.yml.disabled` не включается автоматически.
Фактический отчёт этапа: [docs/pipeline_audit.md](docs/pipeline_audit.md).

## Локальный MinIO

Проверка совместимости S3 не требует Instagram. Сервис доступен только на
`127.0.0.1:9000`, консоль — `127.0.0.1:9001`. Образ собирается из фиксированного
исходного релиза MinIO для локального тестирования; первая сборка может занять
несколько минут. Состояние upstream описано в [docs/instagram.md](docs/instagram.md#локальный-minio).

1. В `.env` задайте собственные локальные `MINIO_TEST_USER` и
   `MINIO_TEST_PASSWORD` (пароль минимум 8 символов).
2. Запустите `docker compose -f docker-compose.minio.yml up --build -d`.
3. В консоли `http://127.0.0.1:9001` создайте бакет `legal-reels-test`.
4. Для локального Python задайте `S3_ENDPOINT=http://127.0.0.1:9000`,
   `S3_BUCKET=legal-reels-test`, `S3_REGION=us-east-1`, `S3_ADDRESSING_STYLE=path`.
   Ключи S3 должны совпадать с выбранными локальными данными MinIO,
   `S3_PUBLIC_BASE_URL` оставьте пустым.
5. Выполните `python -m scripts.check_minio drafts/reels/reel-ID/video.mp4`.
   Скрипт загрузит файл, проверит скачивание по подписанной ссылке и удалит объект.
6. Завершите: `docker compose -f docker-compose.minio.yml down`.

Из Docker Desktop для локального MinIO используйте `host.docker.internal`
вместо `127.0.0.1`. Перед реальной публикацией верните настройки облачного S3
с публичным HTTPS: localhost недоступен серверам Instagram.

## Чек-лист ручной настройки

- [ ] Установить Docker и собрать образ либо подготовить Python и медиазависимости.
- [ ] Создать `.env` из примера, заполнить OpenRouter и доступную модель.
- [ ] Заполнить ElevenLabs: ключ, голос и модель; проверить баланс сервисов.
- [ ] Подготовить Instagram Business/Creator и приложение Meta, выдать разрешения
      публикации; записать ID, токен нужного типа и поддерживаемую версию API.
- [ ] Проверить срок токена и порядок его обновления, требования Meta к доступу.
- [ ] Создать S3-бакет, настроить ключи, endpoint, регион и доступный HTTPS URL.
- [ ] Проверить `sources.yaml`, контакты и оформление в `templates/default.yaml`.
- [ ] Выполнить `run-all --dry-run`, устранить проблемы; затем просмотреть `--stub`.
- [ ] Создать один реальный черновик, вручную сверить нормы, текст, звук и титры.
- [ ] Выполнить `approve`, `publish --dry-run`, затем осознанно `publish`;
      проверить Reel в аккаунте и очистку объекта S3, подтвердить тему `mark-used`.

## Документация и модули

Код разделён на сбор (`source_*`, `topic_*`, `primary_evidence`), сценарий и
проверки (`script_*`, `reel_script`, `legal_references`, `fact_guard`), озвучку
(`tts*`, `elevenlabs_tts`), рендер (`render_*`, `video_renderer`) и публикацию
(`reel_drafts`, `instagram_*`, `video_storage`). Общие настройки — `config` и
`publishing_config`, полная последовательность — `full_pipeline`, проверка
готовности — `pipeline_preflight`, CLI — `cli`.

[Сбор тем](docs/collection.md) · [Сценарии](docs/script.md) ·
[Озвучка](docs/tts.md) · [Рендер](docs/render.md) ·
[Instagram и S3](docs/instagram.md) · [План миграции](docs/migration_plan.md) ·
[Принятые решения](docs/decisions.md)
