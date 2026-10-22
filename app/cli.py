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
from app.script_generator import generate_script, load_script_topic, save_script

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
    args = parser.parse_args(argv)
    if args.command and args.draft:
        parser.error("--draft cannot be combined with a subcommand")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        logging.basicConfig(level=logging.INFO)
        logger.error("Invalid configuration: %s", exc)
        return 2
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        if args.command == "collect":
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
            if args.output is not None and args.output.exists():
                raise ValueError("Output already exists; choose a new --output path")
            topic = load_script_topic(args.input, args.topic_id)
            result = generate_script(topic, settings)
            save_script(result, topic, settings, args.output)
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
    except (ValueError, OSError, sqlite3.Error, OpenRouterError) as exc:
        logger.error("Command failed: %s", exc)
        return 2
