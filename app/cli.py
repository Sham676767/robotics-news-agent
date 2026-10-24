from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from dataclasses import replace
from collections.abc import Sequence
from pathlib import Path

from app.config import Settings
from app.legal_draft import load_legal_draft, save_legal_draft
from app.openrouter_client import OpenRouterError
from app.source_config import load_source_config
from app.topic_collector import collect_topics
from app.topic_history import TopicHistory
from app.script_generator import generate_script, load_script_topic, save_script, save_quarantined_script
from app.script_review import review_script, load_checked_script, digest
from app.tts import TTSError
from app.tts_pipeline import synthesize_audio
from app.video_renderer import RenderError, render_video
from app.full_pipeline import run_all
from app.pipeline_preflight import dry_run
from app.reel_drafts import ReelDrafts
from app.instagram_publisher import publish_draft
from app.instagram_client import InstagramError
from app.video_storage import StorageError
from app.secret_logging import protect_logs

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Legal Reels Agent — основа проекта о праве РФ")
    parser.add_argument("--draft", type=Path, help="Проверить и сохранить локальный JSON-черновик с источниками")
    commands = parser.add_subparsers(dest="command")
    collect = commands.add_parser("collect", help="Собрать и отобрать темы; не помечает их использованными")
    collect.add_argument("--sources", type=Path, default=Path("sources.yaml"))
    collect.add_argument("--count", type=int, help="Количество тем на один ролик")
    collect.add_argument("--max-age-days", type=int, help="Окно свежести в днях")
    collect.add_argument("--history", type=Path)
    collect.add_argument("--output", type=Path)
    mark = commands.add_parser("mark-used", help="Подтвердить фактическое использование тем")
    mark.add_argument("ids", nargs="+")
    mark.add_argument("--sources", type=Path, default=Path("sources.yaml"))
    mark.add_argument("--history", type=Path)
    script = commands.add_parser("script", help="Сценарий одной выбранной темы через OpenRouter")
    script.add_argument("--input", type=Path, default=Path("data/collected_topics.json"))
    script.add_argument("--topic-id", help="Обязательно, если в подборке несколько тем")
    script.add_argument("--output", type=Path, help="Новый JSON-файл; существующий файл не заменяется")
    tts = commands.add_parser("tts", help="Озвучить проверенный сценарий и сохранить тайминги слов")
    tts.add_argument("--input", required=True, type=Path, help="Сценарий JSON с соседним .review.json")
    tts.add_argument("--output-dir", type=Path, help="Папка для новых комплектов аудио и таймингов")
    render = commands.add_parser("render", help="Собрать MP4 из проверенного сценария, аудио и таймингов")
    render.add_argument("--input", required=True, type=Path, help="Сценарий JSON с соседним .review.json")
    render.add_argument("--timings", required=True, type=Path, help="timings.json рядом с audio.wav")
    render.add_argument("--template", type=Path)
    render.add_argument("--clips-dir", type=Path, help="Локальные фоновые клипы; иначе градиент")
    render.add_argument("--output-dir", type=Path)
    pipeline = commands.add_parser("run-all", help="Собрать полные черновики до ручного одобрения")
    pipeline.add_argument("--sources", type=Path, default=Path("sources.yaml"))
    pipeline.add_argument("--count", type=int, default=1, help="Количество роликов, по одной теме в каждом")
    pipeline.add_argument("--clips-dir", type=Path)
    pipeline.add_argument("--dry-run", action="store_true", help="Проверка готовности и план без сети и записи файлов")
    pipeline.add_argument("--stub", action="store_true", help="Тестовый сценарий, локальный тон, реальный рендер")
    prepare = commands.add_parser("prepare", help="Собрать черновик из существующих сценария, TTS и видео")
    prepare.add_argument("--input", required=True, type=Path)
    prepare.add_argument("--timings", required=True, type=Path)
    prepare.add_argument("--video", required=True, type=Path)
    approve = commands.add_parser("approve", help="Подтвердить ручную проверку конкретного ролика и аккаунта")
    approve.add_argument("id")
    publish = commands.add_parser("publish", help="Опубликовать ранее одобренный ролик в Instagram")
    publish.add_argument("id")
    publish.add_argument("--dry-run", action="store_true", help="Проверить одобрение без S3 и Graph API")
    args = parser.parse_args(argv)
    if args.command and args.draft:
        parser.error("--draft cannot be combined with a subcommand")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        logging.basicConfig(level=logging.INFO)
        logger.error("Invalid configuration: %s", exc)
        if args.command == "run-all" and args.dry_run:
            print(json.dumps({"dry_run": True, "ready": False, "issues": [str(exc)]}, ensure_ascii=False))
        return 2
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    protect_logs(settings)
    try:
        if args.command == "run-all":
            result = (dry_run(settings, args.sources, count=args.count, stub=args.stub, clips_dir=args.clips_dir) if args.dry_run
                      else run_all(settings, args.sources, count=args.count, stub=args.stub, clips_dir=args.clips_dir))
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return (0 if result["ready"] else 2) if args.dry_run else (0 if result["status"] == "ok" else 3)
        elif args.command == "prepare":
            reel_id = ReelDrafts(settings).prepare(args.input, args.timings, args.video)
            print(json.dumps({"id": reel_id, "status": "awaiting_approval"}, ensure_ascii=False))
        elif args.command == "approve":
            print(json.dumps(ReelDrafts(settings).approve(args.id), ensure_ascii=False, indent=2))
        elif args.command == "publish":
            print(json.dumps(publish_draft(args.id, settings, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        elif args.command == "collect":
            config = load_source_config(args.sources)
            overrides = {}
            for arg, field in (("count", "topics_per_video"), ("max_age_days", "freshness_days"),
                               ("history", "history_path"), ("output", "output_path")):
                value = getattr(args, arg)
                if value is not None:
                    if isinstance(value, int) and value < 1:
                        raise ValueError(f"{arg} must be positive")
                    overrides[field] = value
            config = replace(config, **overrides)
            report = collect_topics(config, settings)
            print(json.dumps({"status": report["status"], "output": str(config.output_path),
                              "selected_topics": [{"id": item["id"], "title": item["title"], "score": item["score"]}
                                                  for item in report["selected_topics"]]}, ensure_ascii=False, indent=2))
            return 0 if len(report["selected_topics"]) == config.topics_per_video else 3
        elif args.command == "script":
            if args.output is not None and (args.output.exists() or args.output.with_suffix(".review.json").exists()):
                raise ValueError("Output already exists; choose a new --output path")
            topic = load_script_topic(args.input, args.topic_id)
            result = generate_script(topic, settings)
            review = review_script(result, topic, settings)
            if not review.passed:
                save_quarantined_script(result, topic, settings, review)
                return 3
            save_script(result, topic, settings, args.output, review=review)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))
        elif args.command == "tts":
            if args.output_dir is not None:
                settings = replace(settings, tts_output_dir=args.output_dir)
            checked, _, _ = load_checked_script(args.input, settings)
            audio = synthesize_audio(checked.voiceover, settings, script_sha256=digest(checked.to_dict()))
            print(json.dumps(audio.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))
        elif args.command == "render":
            result = render_video(args.input, args.timings, settings, template_path=args.template,
                                  output_dir=args.output_dir, clips_dir=args.clips_dir)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))
        elif args.command == "mark-used":
            path = args.history or load_source_config(args.sources).history_path
            with TopicHistory(path) as history:
                count = history.mark_used(args.ids)
            print(json.dumps({"newly_marked_used": count}, ensure_ascii=False))
        elif args.draft is not None:
            draft, sources = load_legal_draft(args.draft)
            save_legal_draft(draft, sources, settings.drafts_dir)
        else:
            logger.info("Legal Reels Agent: configuration valid; foundation stage ready")
            logger.info("Use --draft PATH to validate and save a local legal text draft")
        return 0
    except (ValueError, OSError, sqlite3.Error, OpenRouterError, TTSError, RenderError, InstagramError, StorageError) as exc:
        logger.error("Command failed: %s", exc)
        return 2
