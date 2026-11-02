"""Offline shot composition and audio mix. No source text enters a shell/filter path."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Callable

from app.music import MusicTrack
from app.render_timeline import Shot


def background_sequence(stage: Path, ffmpeg: str, assets: list[Path], shots: tuple[Shot, ...], run: Callable, *, colors: tuple[str, str] = ("101C32", "244B61")) -> None:
    for i, shot in enumerate(shots):
        frames = round((shot.end - shot.start) * 30)
        image = assets[shot.asset].suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        source = (["-loop", "1", "-framerate", "30"] if image else ["-stream_loop", "-1"]) + ["-i", str(assets[shot.asset])]
        zoom = "min(1.09,1+on*0.0007)" if shot.motion == "push_in" else "max(1,1.09-on*0.0007)"
        filters = ("fps=30,scale=1200:2134:force_original_aspect_ratio=increase,crop=1200:2134,setsar=1,"
                   f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames if image else 1}:s=1080x1920:fps=30,"
                   f"eq=brightness=-0.24:saturation=0.75,drawbox=y=0:h=960:color=0x{colors[0]}@0.12:t=fill,drawbox=y=960:h=960:color=0x{colors[1]}@0.12:t=fill,fade=t=in:st=0:d=0.10,fade=t=out:st={max(0, frames / 30 - .1):.5f}:d=0.10")
        run([ffmpeg, "-v", "error", "-nostdin", "-n", "-filter_threads", "1"] + source +
            ["-an", "-vf", filters, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-threads", "2", "-pix_fmt", "yuv420p", f"shot-{i}.mp4"], cwd=stage)
    (stage / "shots.txt").write_text("".join(f"file 'shot-{i}.mp4'\n" for i in range(len(shots))))


def write_accent(path: Path) -> None:
    rate, duration = 24000, .24
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        samples = bytearray()
        for i in range(round(rate * duration)):
            t = i / rate
            fade = min(1, t / .015) * (1 - t / duration) ** 2
            value = 3200 * fade * math.sin(2 * math.pi * (660 * t - 650 * t * t))
            samples.extend(struct.pack("<h", round(value)))
        output.writeframes(samples)


def mix_video(stage: Path, ffmpeg: str, narration: Path, duration: float, music: MusicTrack | None,
              logo: Path | None, run: Callable) -> None:
    write_accent(stage / "accent.wav")
    inputs = ["-f", "concat", "-safe", "1", "-i", "shots.txt", "-i", str(narration), "-i", "accent.wav"]
    graph = "[0:v]ass=subtitles.ass:fontsdir=fonts[vsub];[1:a]loudnorm=I=-16:TP=-1.5:LRA=7,aresample=48000,asplit=2[voice][detector];"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music.path)]
        graph += ("[3:a]aresample=48000,volume=0.35[music];"
                  "[music][detector]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=250[ducked];"
                  f"[voice][ducked][2:a]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95,atrim=duration={duration:.8f}[a];")
    else:
        graph += f"[detector]anullsink;[voice][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,atrim=duration={duration:.8f}[a];"
    if logo:
        logo_index = 4 if music else 3
        inputs += ["-loop", "1", "-i", str(logo)]
        graph += f"[{logo_index}:v]scale=80:60:force_original_aspect_ratio=decrease[logo];[vsub][logo]overlay=820:370:shortest=1[v]"
    else:
        graph += "[vsub]null[v]"
    run([ffmpeg, "-v", "error", "-nostdin", "-n", "-filter_complex_threads", "1"] + inputs +
        ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-frames:v", str(round(duration * 30)), "-t", f"{duration:.8f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "25M", "-bufsize", "50M", "-threads", "2",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", "video.mp4"], cwd=stage)


def review_images(stage: Path, ffmpeg: str, duration: float, cover_time: float, run: Callable) -> None:
    run([ffmpeg, "-v", "error", "-nostdin", "-n", "-filter_threads", "1", "-ss", f"{cover_time:.3f}", "-i", "video.mp4",
         "-frames:v", "1", "-update", "1", "-q:v", "2", "cover.jpg"], cwd=stage)
    # Sample the middle of each <=3.5-second shot, preserving a readable full-frame sheet.
    count = math.ceil(duration / 3.5)
    step = duration / count
    rows = math.ceil(count / 4)
    run([ffmpeg, "-v", "error", "-nostdin", "-n", "-filter_threads", "1", "-i", "video.mp4", "-vf",
         f"select='gte(t,0.35)*isnan(prev_selected_t)+gte(t-prev_selected_t,{step:.6f})',scale=270:480,tile=4x{rows}:padding=8:margin=8:color=0x101C32",
         "-frames:v", "1", "-update", "1", "-q:v", "2", "contact-sheet.jpg"], cwd=stage)

    # Add time labels outside the sampled frames; the video itself keeps its safe zones.
    from PIL import Image, ImageDraw
    from app.typography import measured_font
    with Image.open(stage / "contact-sheet.jpg") as source:
        canvas = Image.new("RGB", (1120, rows * 512 + 8), "#101C32")
        draw = ImageDraw.Draw(canvas)
        for index in range(count):
            col, row = index % 4, index // 4
            tile = source.crop((8 + col * 278, 8 + row * 488, 8 + col * 278 + 270, 8 + row * 488 + 480))
            x, y = 8 + col * 278, 8 + row * 512
            canvas.paste(tile, (x, y))
            time = .35 + index * math.ceil(step * 30) / 30
            draw.text((x + 6, y + 483), f"{time:05.2f}s", font=measured_font("DejaVu Sans", 18), fill="#7CE5CF")
        canvas.save(stage / "contact-sheet.jpg", quality=93)
