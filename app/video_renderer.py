"""Offline FFmpeg rendering and ffprobe verification of a reviewed legal reel."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.scene_visuals import load_visuals, match_shots
from app.audio_edit import edit_silence
from app.music import licensed_music
from app.render_media import background_sequence, mix_video, review_images
from app.render_timeline import Overlay, overlays_for, shots_for
from app.render_inputs import load_render_audio
from app.render_subtitles import build_subtitles
from app.render_template import load_format_template, load_render_template
from app.script_review import digest, load_checked_script

logger = logging.getLogger(__name__)


class RenderError(RuntimeError):
    """Rendering could not produce a verified, complete video."""


@dataclass(frozen=True, slots=True)
class RenderResult:
    video_path: Path
    metadata_path: Path
    duration_seconds: float
    width: int = 1080
    height: int = 1920

    def to_dict(self) -> dict[str, str | float | int]:
        return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}


def run_media(args: list[str], *, cwd: Path | None = None, timeout: float = 600) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"Media tool unavailable or timed out: {Path(args[0]).name}") from exc
    if result.returncode:
        # FFmpeg output may contain input text/paths. Keep it out of public logs.
        raise RenderError(f"{Path(args[0]).name} failed (exit {result.returncode}); check local media and tool support")
    return result.stdout


def probe_media(path: Path, ffprobe: str = "ffprobe") -> dict:
    try:
        data = json.loads(run_media([ffprobe, "-v", "error", "-show_entries",
                                    "stream=codec_type,codec_name,width,height,pix_fmt,duration:format=duration,format_name",
                                    "-of", "json", str(path.resolve())], timeout=30))
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
            raise ValueError
        return data
    except (ValueError, TypeError) as exc:
        raise RenderError("ffprobe returned invalid metadata") from exc


def verify_video(data: dict, expected: float) -> float:
    try:
        videos = [item for item in data["streams"] if item["codec_type"] == "video"]
        audios = [item for item in data["streams"] if item["codec_type"] == "audio"]
        duration = float(data["format"]["duration"])
        valid = (len(videos) == len(audios) == 1 and videos[0]["codec_name"] == "h264"
                 and videos[0]["width"] == 1080 and videos[0]["height"] == 1920
                 and videos[0]["pix_fmt"] == "yuv420p" and audios[0]["codec_name"] == "aac"
                 and "mp4" in data["format"]["format_name"].split(",")
                 and math.isfinite(duration) and 0 < duration <= 90
                 and abs(duration - expected) <= 0.08
                 and all(abs(float(stream["duration"]) - expected) <= 0.08 for stream in (videos[0], audios[0])))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RenderError("Incomplete rendered video metadata") from exc
    if not valid:
        raise RenderError("Video failed H.264/AAC, 1080x1920 or duration verification")
    return duration



STUB_HEADER = "ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ"


def presentation_header(header: str, *, stub: bool) -> str:
    return STUB_HEADER if stub else ("БИЗНЕС · ПРАВО РФ" if STUB_HEADER in header else header)


def render_video(script_path: Path, timings_path: Path, settings: Settings, *,
                 template_path: Path | None = None, output_dir: Path | None = None,
                 clips_dir: Path | None = None, stub: bool = False) -> RenderResult:
    script, topic, _ = load_checked_script(script_path, settings)
    theme = load_render_template(template_path or settings.render_template)
    original = load_render_audio(timings_path, script)
    if original.duration > 90:
        raise ValueError("Narration exceeds 90 seconds; regenerate shorter speech")
    if not any(source.law and source.article for source in script.sources):
        raise ValueError("Rendering requires a specific legal norm")
    executables = []
    for tool in (settings.ffmpeg_bin, settings.ffprobe_bin):
        located = shutil.which(tool)
        if not located:
            raise RenderError(f"Required media tool is not installed: {tool}")
        executables.append(str(Path(located).resolve()))
    ffmpeg, ffprobe = executables
    if theme.style == "cinematic_still":
        from app.cinematic_renderer import render_cinematic
        return render_cinematic(script, topic, original, settings, theme, stub=stub,
                                output_dir=output_dir, ffmpeg=ffmpeg, ffprobe=ffprobe)
    library = clips_dir if clips_dir is not None else settings.visuals_dir
    visual_assets = load_visuals(library)
    assets = [asset.path for asset in visual_assets]
    music = licensed_music(settings.music_manifest) if settings.music_manifest else None
    if settings.brand_logo and (settings.brand_logo.is_symlink() or not settings.brand_logo.is_file() or
                               settings.brand_logo.suffix.lower() not in {".png", ".jpg", ".jpeg"}):
        raise ValueError("BRAND_LOGO must be a local PNG/JPEG image")
    target = output_dir or settings.render_output_dir
    target.mkdir(parents=True, exist_ok=True)
    final = target / f"render-{uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix=".render-", dir=target) as temporary:
        stage = Path(temporary).resolve()
        from app.typography import font_file
        (stage / "fonts").mkdir()
        shutil.copy2(font_file(theme.font), stage / "fonts/font.ttf")
        edit = edit_silence(original, stage / "narration.wav")
        audio = edit.audio
        # No silent end screen or time-stretching: show CTA while it is spoken.
        frames = math.ceil(audio.duration * 30 - 1e-8)
        duration = frames / 30
        if not 30 <= duration <= 45:
            raise ValueError("Edited narration must last 30–45 seconds; regenerate speech at a calm pace")
        shots = match_shots(shots_for(duration, len(assets)), script, audio, visual_assets)
        cta = settings.client_cta if script.editorial else settings.script_cta
        overlays = overlays_for(script, audio, header=presentation_header(theme.header_text, stub=stub), expert=settings.expert_name or theme.service_name, cta=cta, font=theme.font, maximum_words=theme.words_per_caption, cta_seconds=theme.cta_seconds)
        if settings.brand_logo:
            overlays = tuple(replace(item, bounds=(100, 390, 780, 470)) if item.kind == "expert" else item for item in overlays)
        format_name = script.editorial.format if script.editorial else "question_answer"
        preset = load_format_template(format_name)
        overlays += (Overlay("format", 0, min(3, audio.duration), preset["badge"], (100, 480, 900, 570)),)
        # Three steps follow actual sentence word times, not an unrelated wall-clock rotation.
        paragraphs = script.voiceover.split("\n\n")
        start_index = len(paragraphs[0].split())
        essence_words = audio.words[start_index:start_index + len(paragraphs[1].split())]
        boundaries = [0] + [i + 1 for i, word in enumerate(essence_words) if word.word.endswith((".", "?", "!", ";"))]
        if boundaries[-1] != len(essence_words):
            boundaries.append(len(essence_words))
        for index in range(min(3, len(boundaries) - 1)):
            words = essence_words[boundaries[index]:boundaries[index + 1]]
            if words and words[-1].end > 3:
                overlays += (Overlay("format", max(3, words[0].start), words[-1].end, preset["steps"][index], (100, 480, 900, 570)),)
        end_start = audio.duration - theme.cta_seconds
        overlays = tuple(replace(item, end=min(item.end, end_start)) if item.kind == "format" else item for item in overlays if item.kind != "format" or item.start < end_start)
        if stub:
            overlays = tuple(replace(item, end=audio.duration) if item.kind == "header" else item for item in overlays)
        (stage / "subtitles.ass").write_text(build_subtitles(script, audio, theme, cta, overlays=overlays, cta_keyword=settings.cta_keyword if script.editorial else ""), encoding="utf-8")
        logger.info("Rendering %d moving shots, %.2fs, format=%s", len(shots), duration, format_name)
        background_sequence(stage, ffmpeg, assets, shots, run_media, colors=(theme.background_top, theme.background_bottom))
        mix_video(stage, ffmpeg, audio.path, duration, music, settings.brand_logo.resolve() if settings.brand_logo else None, run_media, cta_start=end_start, cta_background=theme.cta_background)
        probe = probe_media(stage / "video.mp4", ffprobe)
        actual = verify_video(probe, duration)
        cover_time = min(settings.cover_frame_seconds, actual - .1)
        review_images(stage, ffmpeg, actual, cover_time, run_media)
        metadata = {"schema_version": 2, "mode": "stub" if stub else "live", "video_file": "video.mp4", "script_sha256": digest(script.to_dict()),
                    "audio_sha256": original.sha256, "edited_audio_sha256": audio.sha256,
                    "video_sha256": hashlib.sha256((stage / "video.mp4").read_bytes()).hexdigest(),
                    "template": {key: value for key, value in asdict(theme).items() if key not in {"end_seconds", "contact"}}, "background": "clips" if clips_dir else "library",
                    "background_files": [path.name for path in assets], "duration_seconds": actual,
                    "timing_source": audio.timing_source, "probe": probe, "topic": topic.title,
                    "format": format_name, "hook": script.hook, "cta": cta,
                    "cta_keyword": settings.cta_keyword if script.editorial else None,
                    "hook_variants": list(script.editorial.hook_variants) if script.editorial else [script.hook],
                    "selected_hook": script.editorial.selected_hook if script.editorial else 0,
                    "brand": {"expert_name": settings.expert_name or theme.service_name, "logo_sha256": hashlib.sha256(settings.brand_logo.read_bytes()).hexdigest() if settings.brand_logo else None},
                    "publication_date": None, "cover_frame_seconds": cover_time, "cover_file": "cover.jpg",
                    "shots": [asdict(shot) for shot in shots], "overlays": [item.to_dict() for item in overlays],
                    "audio_edit": {"cuts": edit.cuts, "speed": edit.speed, "tail_silence_seconds": edit.tail_silence},
                    "music": {"file": music.path.name, "license": music.license, "attribution": music.attribution, "ducking": True} if music else None,
                    "publication_allowed": False, "human_review_required": True}
        (stage / "render.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (stage / "storyboard.json").write_text(json.dumps({"shots": metadata["shots"], "overlays": metadata["overlays"]}, ensure_ascii=False, indent=2) + "\n")
        keep = {"video.mp4", "subtitles.ass", "render.json", "cover.jpg", "contact-sheet.jpg", "storyboard.json", "narration.wav"}
        for path in stage.iterdir():
            if path.name not in keep:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        if final.exists() or final.is_symlink():
            raise FileExistsError("Render result already exists")
        stage.rename(final)
    logger.info("Verified video and review images saved: %s", final)
    return RenderResult(final / "video.mp4", final / "render.json", actual)
