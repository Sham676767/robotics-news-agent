from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from app.config import Settings
from app.legal_draft import load_legal_draft, save_legal_draft

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Legal Reels Agent — основа проекта о праве РФ")
    parser.add_argument("--draft", type=Path, help="Проверить и сохранить локальный JSON-черновик с источниками")
    args = parser.parse_args(argv)
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
        if args.draft is not None:
            draft, sources = load_legal_draft(args.draft)
            save_legal_draft(draft, sources, settings.drafts_dir)
        else:
            logger.info("Legal Reels Agent: configuration valid; foundation stage ready")
            logger.info("Use --draft PATH to validate and save a local legal text draft")
        return 0
    except (ValueError, OSError) as exc:
        logger.error("Draft processing failed: %s", exc)
        return 2
