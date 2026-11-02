"""Read-only Instagram insights joined to the exact published editorial metadata."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.instagram_client import INSIGHT_METRICS, InstagramClient, InstagramError, graph_id
from app.reel_drafts import ReelDrafts, checksum, read_json
from app.script_review import digest

METRICS = INSIGHT_METRICS
MESSAGES_NOTE = ("Instagram Media Insights не возвращает число входящих сообщений, связанных с конкретным Reel. "
                 "messages=null означает недоступность, а не ноль. Для атрибуции обращений нужны уникальные "
                 "CTA-коды и отдельный учёт сообщений/CRM; общее число сообщений аккаунта сюда не подставляется.")


def published_metadata(folder: Path, settings: Settings) -> dict[str, Any]:
    manifest, state, render = (read_json(folder / name) for name in ("draft.json", "state.json", "render.json"))
    approval = state.get("approval")
    if manifest.get("mode") != "live" or state.get("status") != "published":
        raise ValueError("not_published_live")
    if (not isinstance(approval, dict) or approval.get("account") != settings.publishing.account
            or approval.get("bundle_sha256") != digest(manifest)):
        raise ValueError("published_account_or_bundle_mismatch")
    for name in ("render.json", "script.json"):
        if (folder / name).is_symlink() or checksum(folder / name) != manifest.get("assets", {}).get(name):
            raise ValueError("published_metadata_changed")
    script = read_json(folder / "script.json")
    if render.get("script_sha256") != digest(script):
        raise ValueError("published_script_mismatch")
    publication_date = state.get("publication_date", state.get("published_at"))
    if not isinstance(publication_date, str) or datetime.fromisoformat(publication_date).utcoffset() is None:
        raise ValueError("missing_publication_date")
    metadata = {"id": folder.name, "media_id": graph_id(state.get("media_id")),
                "topic": render.get("topic", read_json(folder / "script.review.json")["topic"]["title"]),
                "format": render.get("format", "legacy"), "hook": script["hook"],
                "hook_variants": render.get("hook_variants", [script["hook"]]),
                "selected_hook": render.get("selected_hook", 0), "duration_seconds": render.get("duration_seconds"),
                "cta": render.get("cta", script["voiceover"].split("\n\n")[-1]),
                "cta_keyword": render.get("cta_keyword"), "publication_date": publication_date}
    return metadata


def comparison(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[field]].append(row)
    result = []
    for name, items in grouped.items():
        # Do not divide partial saves by views from a different set of reels.
        paired = [row for row in items if all(row[metric] is not None for metric in ("views", "saved", "shares"))]
        views = sum(row["views"] for row in paired)
        saved = sum(row["saved"] for row in paired)
        shares = sum(row["shares"] for row in paired)
        result.append({field: name, "reels": len(items), "comparable_reels": len(paired), "views": views if paired else None,
                       "saved": saved if paired else None, "shares": shares if paired else None, "messages": None,
                       "saves_per_1000_views": round(saved / views * 1000, 2) if views else None,
                       "shares_per_1000_views": round(shares / views * 1000, 2) if views else None,
                       "save_share_rate": round((saved + shares) / views, 5) if views else None})
    return sorted(result, key=lambda row: (row["save_share_rate"] is not None, row["save_share_rate"] or 0), reverse=True)


def collect_stats(settings: Settings, *, ids: list[str] | None = None, client: InstagramClient | None = None) -> dict[str, Any]:
    store = ReelDrafts(settings)
    folders = [store.path(value) for value in ids] if ids else sorted(store.root.glob("reel-*"))
    rows, issues = [], []
    for folder in folders:
        if folder.is_symlink() or not folder.is_dir():
            issues.append({"id": folder.name, "reason": "invalid_draft_folder"})
            continue
        try:
            metadata = published_metadata(folder, settings)
        except (ValueError, OSError, KeyError, TypeError, InstagramError) as exc:
            # No upstream response/body or arbitrary on-disk content is echoed.
            if isinstance(exc, ValueError) and str(exc) == "not_published_live" and not ids:
                continue
            issues.append({"id": folder.name, "reason": "invalid_published_metadata"})
            continue
        client = client if client is not None else InstagramClient(settings.publishing)
        try:
            values, unavailable = client.media_insights(metadata["media_id"])
        except InstagramError as exc:
            values = {metric: None for metric in METRICS}
            unavailable = {metric: exc.reason for metric in METRICS}
        rows.append({**metadata, **values, "messages": None, "unavailable": {**unavailable, "messages": "no_per_reel_attribution"}})
    incomplete = any(any(row[metric] is None for metric in METRICS) for row in rows)
    return {"status": "partial" if issues or incomplete else ("ok" if rows else "no_data"),
            "snapshot_at": datetime.now(timezone.utc).isoformat(), "reels": rows, "issues": issues,
            "by_format": comparison(rows, "format"), "by_hook": comparison(rows, "hook"),
            "messages_note": MESSAGES_NOTE,
            "comparison_note": ("Сортировка по доле сохранений и пересылок среди просмотров, только по полным парам метрик. "
                                "Это наблюдение, не причинный A/B-эксперимент: учитывайте возраст публикаций, охват и размер выборки. "
                                "Метрики lifetime не измеряют заявки или досмотры.")}
