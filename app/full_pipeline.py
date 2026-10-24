"""Collect -> reviewed script -> speech -> render -> complete draft; approval is separate."""
from __future__ import annotations

import logging
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.reel_drafts import ReelDrafts, write_json
from app.render_template import load_render_template
from app.script_generator import generate_script, save_script, save_quarantined_script
from app.script_review import digest, review_script
from app.source_config import load_source_config
from app.stub_pipeline import ToneProvider, stub_script
from app.topic_collector import collect_topics
from app.topics import topic_from_dict, topic_to_dict
from app.tts_pipeline import synthesize_audio
from app.video_renderer import render_video

logger = logging.getLogger(__name__)


def run_all(settings: Settings, sources: Path, *, count: int = 1, stub: bool = False,
            clips_dir: Path | None = None) -> dict[str, Any]:
    if not 1 <= count <= 10:
        raise ValueError("Video count must be 1–10")
    is_stub = stub or settings.publishing.pipeline_mode == "stub"
    store = ReelDrafts(settings)
    if is_stub:
        topics = [None] * count
    else:
        config = load_source_config(sources)
        report_path = settings.drafts_dir / "runs" / f"collect-{uuid4().hex}.json"
        report = collect_topics(replace(config, topics_per_video=count, output_path=report_path), settings)
        topics = [topic_from_dict(raw) for raw in report["selected_topics"]]
    results = []
    for topic in topics:
        folder = store.create(mode="stub" if is_stub else "live")
        stage = "script"
        try:
            if is_stub:
                topic, script, review = stub_script(settings)
            else:
                write_json(folder / "topic.json", topic_to_dict(topic))
                script = generate_script(topic, settings)
                write_json(folder / "script.json", script.to_dict())
                (folder / "caption.txt").write_text(script.caption + "\n", encoding="utf-8")
                write_json(folder / "sources.json", {"sources": script.to_dict()["sources"]})
                stage = "source_review"
                review = review_script(script, topic, settings)
                (folder / "script.json").unlink()
            write_json(folder / "topic.json", topic_to_dict(topic))
            if not review.passed:
                write_json(folder / "script.json", script.to_dict())
                write_json(folder / "script.review.json", {"review": review.to_dict(), "topic": topic_to_dict(topic)})
                save_quarantined_script(script, topic, settings, review)
                store.checkpoint(folder, stage="quarantined", review_status="rejected")
                results.append({"id": folder.name, "status": "quarantined"})
                continue
            save_script(script, topic, settings, folder / "script.json", review=review)
            store.checkpoint(folder, stage="tts", review_status="checked")
            stage = "tts"
            audio = synthesize_audio(script.voiceover, replace(settings, tts_output_dir=folder / ".audio"),
                                     provider=ToneProvider() if is_stub else None, script_sha256=digest(script.to_dict()))
            shutil.copy2(audio.audio_path, folder / "audio.wav")
            shutil.copy2(audio.timings_path, folder / "timings.json")
            shutil.rmtree(folder / ".audio")
            store.checkpoint(folder, stage="render")
            stage = "render"
            template = settings.render_template
            if is_stub:
                theme = replace(load_render_template(template), header_text="ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ")
                template = folder / "test-template.yaml"
                import yaml
                template.write_text(yaml.safe_dump(asdict(theme), allow_unicode=True), encoding="utf-8")
            video = render_video(folder / "script.json", folder / "timings.json", settings,
                                 template_path=template, output_dir=folder / ".video", clips_dir=clips_dir)
            for name in ("video.mp4", "render.json", "subtitles.ass"):
                shutil.copy2(video.video_path.parent / name, folder / name)
            shutil.rmtree(folder / ".video")
            store.finish(folder)
            results.append({"id": folder.name, "status": "awaiting_approval" if not is_stub else "stub_preview",
                            "path": str(folder), "video": str(folder / "video.mp4")})
        except (ValueError, OSError, RuntimeError):
            store.checkpoint(folder, stage="failed", error=f"{stage}_failed")
            logger.error("Pipeline stage %s failed; available artifacts retained in draft %s", stage, folder.name)
            results.append({"id": folder.name, "status": "failed", "stage": stage, "path": str(folder)})
    complete = len(results) == count and all(item["status"] in {"awaiting_approval", "stub_preview"} for item in results)
    return {"status": "ok" if complete else "partial", "drafts": results, "requested_count": count,
            "publication_performed": False, "stub": is_stub}
