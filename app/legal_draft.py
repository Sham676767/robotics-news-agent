"""Load, validate and persist local text drafts for editorial review."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.draft_validation import validate_legal_draft
from app.models import LegalDraft, LegalSection, LegalSource

logger = logging.getLogger(__name__)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def load_legal_draft(path: Path) -> tuple[LegalDraft, tuple[LegalSource, ...]]:
    package = _object(json.loads(path.read_text(encoding="utf-8")), "Draft package")
    raw_sources = package.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be an array")
    sources: list[LegalSource] = []
    for value in raw_sources:
        source = _object(value, "Source")
        sources.append(LegalSource(
            title=_text(source, "title"), source=_text(source, "source"),
            url=_text(source, "url"), content=_text(source, "content"),
            jurisdiction=_text(source, "jurisdiction"),
        ))
    raw_draft = _object(package.get("draft"), "draft")
    raw_sections = raw_draft.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError("sections must be an array")
    sections: list[LegalSection] = []
    for value in raw_sections:
        section = _object(value, "Section")
        source_index = section.get("source_index")
        if type(source_index) is not int:
            raise ValueError("source_index must be an integer")
        sections.append(LegalSection(
            headline=_text(section, "headline"), body=_text(section, "body"),
            source_index=source_index,
        ))
    draft = LegalDraft(
        title=_text(raw_draft, "title"), intro=_text(raw_draft, "intro"),
        sections=tuple(sections),
    )
    validate_legal_draft(draft, sources)
    return draft, tuple(sources)


def build_legal_draft(draft: LegalDraft, sources: Sequence[LegalSource]) -> dict[str, Any]:
    validate_legal_draft(draft, sources)
    return {
        "schema_version": 1,
        "status": "review_required",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "draft": asdict(draft),
        "sources": [asdict(source) for source in sources],
        "source_links": [
            {
                "section_index": index,
                "source": sources[section.source_index - 1].source,
                "url": sources[section.source_index - 1].url,
            }
            for index, section in enumerate(draft.sections, start=1)
        ],
    }


def save_legal_draft(draft: LegalDraft, sources: Sequence[LegalSource], output_dir: Path) -> Path:
    # Validate before creating any output and avoid overwriting previous drafts.
    package = build_legal_draft(draft, sources)
    content = json.dumps(package, ensure_ascii=False, indent=2) + "\n"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"legal-draft-{uuid4().hex}.json"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_dir, delete=False) as file:
            temporary_path = Path(file.name)
            file.write(content)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    logger.info("Legal draft saved for review: %s", output_path)
    return output_path
