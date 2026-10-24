"""Offline FFmpeg rendering and ffprobe verification of a reviewed legal reel."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.render_inputs import load_render_audio
from app.render_subtitles import build_subtitles
from app.render_template import RenderTemplate, load_render_template
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


def write_gradient(path: Path, theme: RenderTemplate) -> None:
    top = tuple(int(theme.background_top[i:i + 2], 16) for i in (0, 2, 4))
    bottom = tuple(int(theme.background_bottom[i:i + 2], 16) for i in (0, 2, 4))
    with path.open("wb") as file:
        file.write(b"P6\n1080 1920\n255\n")
        for row in range(1920):
            pixel = bytes(round(a + (b - a) * row / 1919) for a, b in zip(top, bottom))
            file.write(pixel * 1080)


def render_video(script_path: Path, timings_path: Path, settings: Settings, *,
                 template_path: Path | None = None, output_dir: Path | None = None,
                 clips_dir: Path | None = None) -> RenderResult:
    script, _, _ = load_checked_script(script_path, settings)
    theme = load_render_template(template_path or settings.render_template)
    audio = load_render_audio(timings_path, script)
    duration = audio.duration + theme.end_seconds
    # Round frame count down so muxing never pushes a nominal 90 seconds past the limit.
    frames = math.floor(duration * 30 + 1e-8)
    if duration > 90 or frames / 30 < duration - 0.034:
        raise ValueError("Narration plus end screen must fit within 90 seconds; regenerate shorter speech")
    if not any(source.law and source.article for source in script.sources):
        raise ValueError("Rendering requires a specific legal norm")
    for source in script.sources:
        if source.law and source.article and len(source.law + source.article + source.part + source.url) > 320:
            raise ValueError("Norm card is too long for the template; choose a more compact source record")
    executables = []
    for tool in (settings.ffmpeg_bin, settings.ffprobe_bin):
        located = shutil.which(tool)
        if not located:
            raise RenderError(f"Required media tool is not installed: {tool}")
        executables.append(str(Path(located).resolve()))
    ffmpeg, ffprobe = executables
    clips: list[Path] = []
    if clips_dir is not None:
        if not clips_dir.is_dir():
            raise ValueError("Background clips directory does not exist")
        clips = sorted(path.resolve() for path in clips_dir.iterdir()
                       if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"})
        if not clips or len(clips) > 20:
            raise ValueError("Background folder must contain 1–20 local video clips")
        for clip in clips:
            if not any(item.get("codec_type") == "video" for item in probe_media(clip, ffprobe)["streams"]):
                raise ValueError("Background clip has no video stream")
    target = output_dir or settings.render_output_dir
    target.mkdir(parents=True, exist_ok=True)
    final = target / f"render-{uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix=".render-", dir=target) as temporary:
        stage = Path(temporary).resolve()
        (stage / "subtitles.ass").write_text(build_subtitles(script, audio, theme, settings.script_cta), encoding="utf-8")
        # All filter-referenced names are fixed local names, never interpolated source text.
        base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-filter_threads", "1"]
        if clips:
            # Normalize each local clip before concat: mixed sizes/fps/codecs are supported.
            for index, clip in enumerate(clips):
                run_media(base + ["-i", str(clip), "-t", f"{duration:.8f}", "-an", "-vf",
                                 "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
                                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                                 f"clip-{index}.mp4"], cwd=stage)
            (stage / "clips.txt").write_text("".join(f"file 'clip-{i}.mp4'\n" for i in range(len(clips))), encoding="utf-8")
            background = ["-stream_loop", "-1", "-f", "concat", "-safe", "1", "-i", "clips.txt"]
            filters = "eq=brightness=-0.20,ass=subtitles.ass"
        else:
            write_gradient(stage / "background.ppm", theme)
            background = ["-loop", "1", "-framerate", "30", "-i", "background.ppm"]
            filters = "ass=subtitles.ass"
        logger.info("Rendering %s background, %.2fs, timing_source=%s", "clips" if clips else "gradient", duration, audio.timing_source)
        run_media(base + background + ["-i", str(audio.path), "-map", "0:v:0", "-map", "1:a:0",
                                     "-vf", filters, "-af", f"apad,atrim=duration={frames / 30:.8f}",
                                     "-frames:v", str(frames), "-t", f"{frames / 30:.8f}",
                                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2",
                                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                                     "-movflags", "+faststart", "video.mp4"], cwd=stage)
        probe = probe_media(stage / "video.mp4", ffprobe)
        actual = verify_video(probe, duration)
        metadata = {"schema_version": 1, "video_file": "video.mp4", "script_sha256": digest(script.to_dict()),
                    "audio_sha256": audio.sha256, "video_sha256": hashlib.sha256((stage / "video.mp4").read_bytes()).hexdigest(),
                    "template": asdict(theme), "background": "clips" if clips else "gradient",
                    "background_files": [path.name for path in clips], "duration_seconds": actual,
                    "timing_source": audio.timing_source, "probe": probe,
                    "publication_allowed": False, "human_review_required": True}
        (stage / "render.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        # Keep only reviewable outputs, not potentially large normalized temporary clips.
        for path in stage.iterdir():
            if path.name not in {"video.mp4", "subtitles.ass", "render.json"}:
                path.unlink()
        if final.exists() or final.is_symlink():
            raise FileExistsError("Render result already exists")
        stage.rename(final)
    logger.info("Verified video saved: %s", final)
    return RenderResult(final / "video.mp4", final / "render.json", actual)
