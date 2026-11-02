"""Single-scene compositor; validation and publication gates remain in video_renderer."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from typing import TYPE_CHECKING

from app.config import Settings
from app.reel_script import ReelScript
from app.render_inputs import RenderAudio
from app.render_template import RenderTemplate
from app.topics import Topic

if TYPE_CHECKING:
    from app.video_renderer import RenderResult

from app.audio_edit import edit_silence
from app.backgrounds import StubBackgroundProvider, reserve_library_background
from app.cinematic_captions import cinematic_subtitles
from app.cinematic_media import video_graph, overlay_inputs
from app.music import licensed_music
from app.render_media import review_images
from app.typography import font_file

logger = logging.getLogger(__name__)


def render_cinematic(script: ReelScript, topic: Topic, original: RenderAudio, settings: Settings, theme: RenderTemplate, *,
                     stub: bool, output_dir: Path | None, ffmpeg: str, ffprobe: str) -> RenderResult:
    from app.video_renderer import RenderResult, run_media, probe_media, verify_video
    from app.script_review import digest
    target = output_dir or settings.render_output_dir
    target.mkdir(parents=True, exist_ok=True)
    final = target / ('render-' + uuid4().hex)
    handle = settings.brand_handle or ('@LEGAL_DEMO' if stub else '')
    if not stub and not handle:
        raise ValueError('BRAND_HANDLE is required for cinematic_still')
    music = licensed_music(settings.music_manifest) if settings.music_manifest else None
    if music is None:
        raise ValueError('cinematic_still requires licensed music for the brand ending')
    with tempfile.TemporaryDirectory(prefix='.cinematic-', dir=target) as folder:
        stage = Path(folder).resolve()
        (stage/'fonts').mkdir()
        shutil.copy2(font_file(theme.font), stage/'fonts/font.ttf')
        edit = edit_silence(original, stage/'narration.wav')
        audio = edit.audio
        duration = math.ceil((audio.duration+1.5)*30)/30
        if not 30 <= duration <= 45:
            raise ValueError('cinematic_still requires speech plus 1.5-second brand ending to fit 30–45 seconds')
        if settings.background_provider == 'stub' or (stub and not (settings.backgrounds_dir/settings.background_tag).is_dir()):
            background = StubBackgroundProvider(stage).get(settings.background_tag)
        else:
            background = reserve_library_background(settings.backgrounds_dir, settings.background_tag,
                                                    settings.drafts_dir/'background-rotation.sqlite3')
        props_path = background.path.with_suffix('.json')
        props = json.loads(props_path.read_text()) if props_path.exists() else {}
        fire_box = tuple(props.get('fire_box', (.65,.48,.2,.18)))
        light_box = tuple(props.get('light_box', (.35,.3,.5,.45)))
        for box in (fire_box, light_box):
            if len(box) != 4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box) or box[2] <= 0 or box[3] <= 0 or box[0]+box[2]>1 or box[1]+box[3]>1:
                raise ValueError('Invalid local effect mask bounds')
        subtitles, records = cinematic_subtitles(script,audio,theme,brand_handle=handle,stub=stub,logo=bool(settings.brand_logo),cta_keyword=settings.cta_keyword)
        (stage/'subtitles.ass').write_text(subtitles)
        image = background.path.suffix.lower() in {'.png','.jpg','.jpeg'}
        inputs = (['-loop','1','-framerate','30'] if image else ['-stream_loop','-1']) + ['-i',str(background.path)]
        inputs += ['-i',str(audio.path),'-stream_loop','-1','-i',str(music.path)]
        inputs += overlay_inputs(settings.overlays_dir)
        if settings.brand_logo:
            if settings.brand_logo.is_symlink() or not settings.brand_logo.is_file():
                raise ValueError('BRAND_LOGO must be a local image')
            inputs += ['-loop','1','-framerate','30','-i',str(settings.brand_logo.resolve())]
        graph = video_graph(duration,fire_box,light_box,logo=bool(settings.brand_logo))
        graph += ("[1:a]apad=pad_dur=1.5,aresample=48000,asplit=2[voice][detector];"
                  "[2:a]aresample=48000,volume=0.15[bed];"
                  "[bed][detector]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=250[ducked];"
                  f"[voice][ducked]amix=inputs=2:duration=first:normalize=0,atrim=duration={duration},loudnorm=I=-16:TP=-1.3:LRA=7[a]")
        run_media([ffmpeg,'-v','error','-nostdin','-n','-filter_complex_threads','1']+inputs+
                  ['-filter_complex',graph,'-map','[v]','-map','[a]','-t',str(duration),'-r','30',
                   '-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-color_range','tv',
                   '-c:a','aac','-b:a','128k','-ar','48000','-movflags','+faststart','video.mp4'],cwd=stage)
        probe=probe_media(stage/'video.mp4',ffprobe);actual=verify_video(probe,duration)
        review_images(stage,ffmpeg,actual,settings.cover_frame_seconds,run_media,count=12)
        metadata={'schema_version':2,'mode':'stub' if stub else 'live','style':'cinematic_still','video_file':'video.mp4',
                  'script_sha256':digest(script.to_dict()),'audio_sha256':original.sha256,'edited_audio_sha256':audio.sha256,
                  'video_sha256':hashlib.sha256((stage/'video.mp4').read_bytes()).hexdigest(),
                  'background':{'provider':background.provider,'file':background.path.name,'fire_box':fire_box,'light_box':light_box},'template':asdict(theme),'duration_seconds':actual,'timing_source':audio.timing_source,'probe':probe,
                  'topic':topic.title,'format':script.editorial.format if script.editorial else 'question_answer',
                  'hook':script.hook,'cta':settings.client_cta if script.editorial else settings.script_cta,
                  'cta_keyword':settings.cta_keyword,'selected_hook':script.editorial.selected_hook if script.editorial else 0,
                  'hook_variants':list(script.editorial.hook_variants) if script.editorial else [script.hook],
                  'brand':{'handle':handle,'expert_name':settings.expert_name,'logo_sha256':hashlib.sha256(settings.brand_logo.read_bytes()).hexdigest() if settings.brand_logo else None},
                  'publication_date':None,'cover_frame_seconds':settings.cover_frame_seconds,'cover_file':'cover.jpg',
                  'shots':[{'start':0,'end':actual,'asset':background.path.name,'motion':'locked'}],'overlays':records,
                  'audio_edit':{'cuts':edit.cuts,'speed':1,'tail_silence_seconds':edit.tail_silence},
                  'music':{'file':music.path.name,'license':music.license,'attribution':music.attribution,'ducking':True},
                  'publication_allowed':False,'human_review_required':True}
        (stage/'render.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
        (stage/'storyboard.json').write_text(json.dumps({'shots':metadata['shots'],'overlays':records},ensure_ascii=False,indent=2))
        for path in list(stage.iterdir()):
            if path.name not in {'video.mp4','render.json','subtitles.ass','narration.wav','cover.jpg','contact-sheet.jpg','storyboard.json'}:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        stage.rename(final)
    logger.info('Rendered cinematic_still: %.2fs, one locked scene', actual)
    return RenderResult(final/'video.mp4',final/'render.json',actual)
