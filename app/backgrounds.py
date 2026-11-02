"""Offline background selection and explicit, confirmed batch image generation."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx
from PIL import Image


@dataclass(frozen=True, slots=True)
class Background:
    path: Path
    tag: str
    provider: str


class BackgroundProvider(Protocol):
    def get(self, tag: str, *, variant: int = 0) -> Background: ...


def validate_tag(tag: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", tag):
        raise ValueError("Background tag must be a safe lowercase name")
    return tag


class LibraryBackgroundProvider:
    def __init__(self, root: Path):
        self.root = root

    def get(self, tag: str, *, variant: int = 0) -> Background:
        folder = self.root / validate_tag(tag)
        files = sorted(p for p in folder.glob('*') if p.is_file() and not p.is_symlink()
                       and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.mp4', '.webm'})
        if not files:
            raise ValueError("No local background for the requested scene tag; generate backgrounds separately")
        return Background(files[variant % len(files)], tag, 'library')


class StubBackgroundProvider:
    def __init__(self, root: Path):
        self.root = root

    def get(self, tag: str, *, variant: int = 0) -> Background:
        validate_tag(tag)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / 'stub.png'
        if not path.exists():
            Image.new('RGB', (1080, 1920), '#77604b').save(path)
        return Background(path, tag, 'stub')


class ImageBackgroundProvider:
    """OpenRouter adapter. Never called from the normal rendering pipeline."""
    def __init__(self, root: Path, api_key: str, model: str, prompt: str):
        self.root, self._key, self.model, self.prompt = root, api_key, model, prompt

    def destination(self, tag: str, variant: int) -> Path:
        validate_tag(tag)
        identity = json.dumps([self.model, self.prompt, variant], ensure_ascii=False)
        name = hashlib.sha256(identity.encode()).hexdigest()[:24]
        return self.root / tag / (name + '.png')

    def get(self, tag: str, *, variant: int = 0) -> Background:
        path = self.destination(tag, variant)
        if path.is_file():
            return Background(path, tag, 'image-cache')
        if not self._key:
            raise ValueError('OPENROUTER_API_KEY is required for background generation')
        prompt = self.prompt + f'\nComposition variant: {variant + 1}. Portrait 9:16, at least 1080x1920.'
        headers = {'Authorization': 'Bearer ' + self._key}
        # No retries on ambiguous transport failures: a paid request may have completed.
        try:
            response = httpx.post('https://openrouter.ai/api/v1/images/generations', headers=headers,
                                  json={'model': self.model, 'prompt': prompt, 'n': 1, 'size': '1152x2048',
                                        'response_format': 'b64_json'}, timeout=180)
            if response.status_code in {404, 405, 422}:
                response = httpx.post('https://openrouter.ai/api/v1/chat/completions', headers=headers,
                    json={'model': self.model, 'messages': [{'role': 'user', 'content': prompt}],
                          'modalities': ['image', 'text'], 'image_config': {'aspect_ratio': '9:16', 'image_size': '2K'}}, timeout=180)
            if response.status_code != 200:
                raise ValueError(f'Background provider rejected request (HTTP {response.status_code})')
            data = response.json()
            if 'data' in data:
                encoded = data['data'][0]['b64_json']
            else:
                url = data['choices'][0]['message']['images'][0]['image_url']['url']
                if not re.match(r'^data:image/(png|jpeg|webp);base64,', url):
                    raise ValueError('Expected an embedded image, not a remote URL')
                encoded = url.split(',', 1)[1]
            if not isinstance(encoded, str) or len(encoded) > 40_000_000:
                raise ValueError('Invalid image size')
            raw = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(raw)) as source:
                source.load()
                width, height = source.size
                if width < 1080 or height < 1920 or abs(width / height - 9 / 16) > .005:
                    raise ValueError('Background must be 9:16 and at least 1080x1920')
                image = source.convert('RGB')
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            raise ValueError('Background generation failed; check provider availability') from None
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.pending.png')
        image.save(temporary)
        metadata = {'prompt': prompt, 'model': self.model, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'tag': tag, 'variant': variant, 'width': width, 'height': height,
                    'sha256': hashlib.sha256(temporary.read_bytes()).hexdigest()}
        path.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        temporary.replace(path)
        return Background(path, tag, 'image')


def generate_batch(provider: ImageBackgroundProvider, tag: str, count: int, *, yes: bool = False) -> dict:
    validate_tag(tag)
    if not 1 <= count <= 10:
        raise ValueError('Background count must be 1–10')
    missing = [i for i in range(count) if not provider.destination(tag, i).is_file()]
    plan = {'count': count, 'cached': count-len(missing), 'estimated_generations': len(missing),
            'maximum_http_requests': 2*len(missing), 'model': provider.model,
            'confirmation_required': bool(missing) and not yes}
    if missing and not yes:
        return plan
    plan['files'] = [str(provider.get(tag, variant=i).path) for i in range(count)]
    return plan
