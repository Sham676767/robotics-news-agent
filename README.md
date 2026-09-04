# Robotics News Agent

24/7 AI-агент для мониторинга новостей о робототехнике, робособаках, гуманоидных роботах и экзоскелетах с ежедневной публикацией дайджеста в 09:00 МСК.

## Цель MVP

Собрать бесплатный/дешёвый конвейер:

1. Сбор новостей из RSS и веб-источников.
2. Определение языка и нормализация.
3. Фильтрация по тематике робототехники.
4. Дедупликация событий.
5. Ранжирование кандидатов.
6. OpenRouter со строгим JSON-выводом для отбора TOP-5 и редакторской обработки.
7. Подготовка изображений.
8. Публикация через VK API.
9. Автоматический запуск 24/7 и публикация в 09:00 Europe/Moscow.

## Ограничение бюджета

До первой публикации общий бюджет: **0–3000 ₽**, приоритет — максимально близко к 0 ₽.

Секреты и API-ключи никогда не хранятся в Git.

## Статус

MVP находится в разработке. Основной pipeline уже покрыт автоматическими тестами; перед переносом на VPS проверяем полноценный production-прогон.

## Архитектура

```text
Sources → Collector → Normalize → Relevance → Dedup → Ranking
                                                        ↓
                                              OpenRouter
                                                        ↓
                                            Editor → Images → VK
                                                        ↓
                                                   09:00 MSK
```

## Локальный запуск

Требуется **Python 3.11+**.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python -m app
```

## Конфигурация

Скопировать `.env.example` в `.env` и заполнить только необходимые переменные. Для OpenRouter нужен ключ в `OPENROUTER_API_KEY`; по умолчанию используется бесплатный роутер `openrouter/free`, а конкретную или платную модель можно задать через `OPENROUTER_MODEL`. Файл `.env` не должен попадать в Git.


## Развёртывание на VPS

Поддерживается Ubuntu/Debian VPS с Docker Engine и Docker Compose plugin.

1. На сервере клонировать репозиторий в `/opt/robotics-news-agent`.
2. Скопировать `.env.example` в `.env`, записать реальные ключи только на сервере и оставить `VK_PUBLISH_REQUIRED=false`.
3. Собрать и проверить черновик без публикации:

   ```bash
   cd /opt/robotics-news-agent
   docker compose build
   docker compose run --rm agent
   ```

4. Проверить статью и TOP-5 в `articles/` и `data/`. Затем установить `VK_PUBLISH_REQUIRED=true` и `VK_PUBLISH_ENABLED=true` в `.env`. До этого момента статья только сохраняется для редакторской проверки.
5. Скопировать unit-файлы, включить ежедневный запуск в 09:00 МСК и убедиться, что он запланирован:

   ```bash
   sudo cp deploy/vps/robotics-news-agent.service /etc/systemd/system/
   sudo cp deploy/vps/robotics-news-agent.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now robotics-news-agent.timer
   systemctl list-timers robotics-news-agent.timer
   ```

Перед включением VPS-таймера нужно отключить ежедневный workflow `Daily Robotics Publisher` в GitHub Actions, иначе оба контура смогут опубликовать один и тот же выпуск.

Журналы VPS: `journalctl -u robotics-news-agent.service -n 200 --no-pager`.
