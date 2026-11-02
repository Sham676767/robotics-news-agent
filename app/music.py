"""Only explicitly licensed local tracks can enter a render."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class MusicTrack:
    path: Path
    license: str
    attribution: str


def licensed_music(manifest: Path) -> MusicTrack:
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise ValueError("Invalid music licence YAML") from None
    if (not isinstance(data, dict) or set(data) != {"file", "license", "commercial_use", "source", "attribution"}
            or data["commercial_use"] is not True or data["license"] not in {"CC0-1.0", "CC-BY-4.0", "original", "licensed"}
            or any(not isinstance(data[key], str) for key in ("file", "license", "source", "attribution"))
            or not data["source"].strip()):
        raise ValueError("Music requires a licence record permitting commercial use")
    name = Path(data["file"])
    if name.is_absolute() or len(name.parts) != 1 or name.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac"}:
        raise ValueError("Music must be a file next to its licence manifest")
    path = manifest.parent / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("Licensed music file is missing or is a symlink")
    if data["license"] == "CC-BY-4.0" and not data["attribution"].strip():
        raise ValueError("CC-BY music requires attribution")
    return MusicTrack(path.resolve(), data["license"], data["attribution"])
