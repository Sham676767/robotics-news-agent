"""Match explicit, timed script scene tags to a local, tagged visual library."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from app.reel_script import ReelScript
from app.render_inputs import RenderAudio
from app.render_timeline import Shot
from app.tts import word_spans

EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True, slots=True)
class VisualAsset:
    path: Path
    tags: frozenset[str]


def load_visuals(folder: Path) -> tuple[VisualAsset, ...]:
    if not folder.is_dir():
        raise ValueError("Background library directory does not exist")
    manifest = folder / "library.yaml"
    try:
        entries = yaml.safe_load(manifest.read_text()) if manifest.exists() else [
            {"file": path.name, "tags": []} for path in sorted(folder.iterdir()) if path.suffix.lower() in EXTENSIONS]
    except yaml.YAMLError:
        raise ValueError("Invalid visual library YAML") from None
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ValueError("Background folder must contain 1–20 local images or video clips")
    result = []
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"file", "tags"} or
                not isinstance(entry["file"], str) or Path(entry["file"]).name != entry["file"] or
                not isinstance(entry["tags"], list) or any(not isinstance(tag, str) or
                    not re.fullmatch(r"[a-z][a-z_]{0,31}", tag) for tag in entry["tags"])):
            raise ValueError("Visual entries require a local filename and lowercase tags")
        path = folder / entry["file"]
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError("Visual asset must be a local image or video")
        result.append(VisualAsset(path.resolve(), frozenset(entry["tags"])))
    if len({asset.path for asset in result}) != len(result):
        raise ValueError("Duplicate visual asset")
    return tuple(result)


def match_shots(shots: tuple[Shot, ...], script: ReelScript, audio: RenderAudio,
                assets: tuple[VisualAsset, ...]) -> tuple[Shot, ...]:
    cues = []
    if script.editorial:
        normalized = " ".join(script.voiceover.split())
        spans = word_spans(normalized)
        cursor = 0
        for scene in script.editorial.scenes:
            fragment = " ".join(scene.text.split())
            start = normalized.index(fragment, cursor)
            end = start + len(fragment)
            indexes = [i for i, span in enumerate(spans) if span.start() < end and span.end() > start]
            if indexes:
                cues.append((audio.words[indexes[0]].start, audio.words[indexes[-1]].end, frozenset(scene.tags)))
            cursor = end
    result, uses = [], [0] * len(assets)
    for shot in shots:
        overlap, tags = max(((max(0, min(shot.end, end) - max(shot.start, start)), tags)
                            for start, end, tags in cues), default=(0, frozenset()), key=lambda pair: pair[0])
        candidates = [i for i, asset in enumerate(assets) if overlap > 0 and tags & asset.tags and "background" not in tags]
        selected = min(candidates, key=lambda i: (-len(tags & assets[i].tags), uses[i], i)) if candidates else -1
        if selected >= 0:
            uses[selected] += 1
        result.append(replace(shot, asset=selected, tags=tuple(sorted(tags))))
    return tuple(result)
