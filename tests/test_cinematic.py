import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from app.backgrounds import reserve_library_background
from app.caption_phrases import dangling, starts_particle
from app.cinematic_captions import cinematic_subtitles, cinematic_phrases
from app.cinematic_media import video_graph
from app.config import Settings
from app.editorial import parse_editorial
from app.render_inputs import RenderAudio
from app.render_template import RenderTemplate, load_render_template
from app.stub_pipeline import stub_script
from app.tts import estimate_word_timings


@pytest.fixture
def cinematic():
    _,script,_=stub_script(Settings())
    audio=RenderAudio(Path('unused.wav'),'unused',39,estimate_word_timings(script.voiceover,39),'estimated')
    return script,audio


def test_cinematic_default_and_legacy_template():
    assert load_render_template(Path('templates/default.yaml')).style=='cinematic_still'
    assert load_render_template(Path('templates/engaging.yaml')).style=='engaging'


@pytest.mark.parametrize('stub',[True,False])
def test_uppercase_hard_cut_karaoke_safe_zones_and_brand_only_ending(cinematic,stub):
    script,audio=cinematic
    ass,records=cinematic_subtitles(script,audio,RenderTemplate(),brand_handle='@EXPERT',stub=stub)
    assert ('ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ' in ass) is stub
    assert r'\fad' not in ass and r'\move' not in ass and r'\1a&H66&' in ass
    assert ',1,2,1,5,' in ass and ',3,18,0,5,' not in ass
    for item in records:
        assert 90<=item['bounds'][0]<item['bounds'][2]<=930
        assert 250<=item['bounds'][1]<item['bounds'][3]<=1520
        if item['start']>=audio.duration:assert item['kind']=='brand'
        if item['kind']=='caption':
            assert 2<=len(item['text'].split())<=4
            assert item['text']==item['text'].upper()
            assert not dangling(item['text']) and not starts_particle(item['text'])
            assert not item['text'].endswith((',',':',';','—','.','!','?'))
            assert item['font_size']==60 and item['karaoke']
    assert script.disclaimer not in ass and 'http' not in ass
    assert max(r['end'] for r in records if r['kind']=='caption')<=audio.duration


def test_emphasis_is_twice_size_without_duplicate_spoken_words(cinematic):
    script,audio=cinematic
    script=replace(script,editorial=replace(script.editorial,emphasis=('риск?',)))
    _,records=cinematic_subtitles(script,audio,RenderTemplate(),brand_handle='@EXPERT',stub=True)
    large=[r for r in records if r['kind']=='emphasis']
    assert len(large)==1 and large[0]['font_size']==120
    seen=[w for r in records if r['kind'] in {'caption','emphasis'} for w in r['words']]
    assert [w['word'] for w in seen]==[w.word for w in audio.words]


def test_emphasis_requires_whole_spoken_words(cinematic):
    _,audio=cinematic
    with pytest.raises(ValueError,match='complete spoken'):
        cinematic_phrases(audio.words,('Дог',),RenderTemplate())


def test_cinematic_filters_lock_camera_mask_fire_screen_dust_and_fade_to_quarter():
    graph=video_graph(40.5,(.65,.48,.2,.18),(.35,.3,.5,.45),logo=True)
    assert 'zoompan' not in graph and 'pan=' not in graph
    assert 'alphamerge' in graph and 'all_mode=screen' in graph
    assert 'sin(2*PI*t/3)' in graph and "A*0.25+B*0.75" in graph
    assert 'st=39.000000:d=1.5' in graph
    assert 'overlay=(W-w)/2:820' in graph


def test_rotation_shared_by_draft_directories_and_does_not_touch_topic_history(tmp_path):
    root=tmp_path/'library';(root/'document').mkdir(parents=True)
    for i in range(3):Image.new('RGB',(1080,1920)).save(root/'document'/f'{i}.png')
    state=tmp_path/'drafts/rotation.sqlite3'
    selected=[reserve_library_background(root,'document',state).path.name for _ in range(4)]
    assert selected==['0.png','1.png','2.png','0.png']
    assert not (tmp_path/'history.sqlite3').exists()


def test_brand_config_loaded_and_invalid_provider_rejected():
    s=Settings.from_env({'BRAND_HANDLE':'@expert','BACKGROUND_PROVIDER':'stub'})
    assert s.brand_handle=='@expert' and s.background_provider=='stub'
    with pytest.raises(ValueError):Settings(background_provider='image')


def test_scene_emphasis_roundtrip(cinematic):
    script,_=cinematic
    value=script.editorial.to_dict();value['emphasis']=['Договор']
    assert parse_editorial(value,script.hook,script.voiceover).emphasis==('Договор',)
    value['emphasis']=['Вымышленная новая фраза']
    with pytest.raises(ValueError):parse_editorial(value,script.hook,script.voiceover)


def test_real_cinematic_stub_render_and_metrics(tmp_path,monkeypatch):
    if not all(shutil.which(t) for t in ('ffmpeg','ffprobe')):pytest.skip('Run in Docker')
    from app.full_pipeline import run_all
    from app.video_renderer import run_media
    from app.audio_edit import silence_ranges
    settings=Settings(drafts_dir=tmp_path/'drafts',render_output_dir=tmp_path/'renders',brand_handle='@LEGAL_DEMO')
    result=run_all(settings,Path('sources.yaml'),stub=True)
    assert result['status']=='ok',result
    folder=Path(result['drafts'][0]['path']);data=json.loads((folder/'render.json').read_text())
    assert data['style']=='cinematic_still' and len(data['shots'])==1 and data['shots'][0]['motion']=='locked'
    assert 30<=data['duration_seconds']<=45 and data['probe']['streams'][0]['width']==1080
    assert data['probe']['streams'][0]['height']==1920
    assert 'ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ' in (folder/'subtitles.ass').read_text()
    with Image.open(folder/'contact-sheet.jpg') as image: assert image.size==(1120,1544)
    # Scene detection runs on encoded pixels, not only on metadata.
    output=run_media(['ffmpeg','-hide_banner','-i',str(folder/'video.mp4'),'-vf',"select='gt(scene,0.3)',metadata=print:file=-",'-an','-f','null','-'])
    assert 'lavfi.scene_score' not in output
    decoded=folder/'decoded.wav'
    run_media(['ffmpeg','-v','error','-i',str(folder/'video.mp4'),'-vn','-ac','1','-ar','24000','-c:a','pcm_s16le',str(decoded)])
    quiet=silence_ranges(decoded)
    assert not quiet or quiet[-1][1]<data['duration_seconds']-.1 or quiet[-1][1]-quiet[-1][0]<=.5
    # Loudnorm exposes measured integrated loudness / true peak via a controlled subprocess.
    import subprocess,re
    measured=subprocess.run(['ffmpeg','-hide_banner','-i',str(folder/'video.mp4'),'-af','loudnorm=I=-16:TP=-1:LRA=7:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
    values=json.loads(re.search(r'\{[^{}]+"input_i"[^{}]+\}',measured.stderr).group())
    assert abs(float(values['input_i'])+16)<=1
    assert float(values['input_tp'])<=-0.8
    # Final mix and sample checks are retained with the reviewable draft.
    (folder/'verification.json').write_text(json.dumps({'integrated_lufs':float(values['input_i']),
        'true_peak_dbtp':float(values['input_tp']),'scene_cuts_above_0_3':0,'contact_sheet_frames':12},indent=2))
    for time in (.5,data['duration_seconds']-.3):
        image_path=folder/f'safe-{time:.1f}.png'
        run_media(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=1080x1920:r=30:d=0.04',
                   '-vf',f'setpts=PTS+{time}/TB,ass=subtitles.ass','-frames:v','1','-update','1',image_path.name],cwd=folder)
        with Image.open(image_path) as frame:
            assert frame.crop((0,0,1080,250)).getbbox() is None
            assert frame.crop((0,1520,1080,1920)).getbbox() is None
            assert frame.crop((930,0,1080,1920)).getbbox() is None
        image_path.unlink()
    # The CTA keyword is timed within the last eight seconds before the brand ending.
    end=data['duration_seconds']-1.5
    assert any('РАЗБОР' in item['text'] and item['start']>=end-8 and item['end']<=end+.04 for item in data['overlays'])
    decoded.unlink()
    import os
    if destination:=os.environ.get('CINEMATIC_DEMO_DIR'):shutil.copytree(folder,Path(destination)/'stub-demo',dirs_exist_ok=True)


def test_cinematic_preflight_is_offline_read_only(tmp_path,monkeypatch):
    from app.pipeline_preflight import dry_run
    from unittest.mock import Mock
    import httpx
    settings=Settings(backgrounds_dir=tmp_path/'missing-library',brand_handle='')
    monkeypatch.setattr(httpx,'post',Mock(side_effect=AssertionError('No paid generation')))
    before=set(tmp_path.rglob('*'))
    report=dry_run(settings,Path('sources.yaml'),stub=True)
    assert report['background_generation_calls']==0 and report['external_calls']==[]
    assert set(tmp_path.rglob('*'))==before
    live=dry_run(settings,Path('sources.yaml'))
    assert any('BRAND_HANDLE' in problem for problem in live['issues'])
    assert any('BACKGROUND_TAG' in problem for problem in live['issues'])


def test_impossible_particle_boundaries_fail_closed():
    with pytest.raises(ValueError):
        cinematic_phrases(estimate_word_timings('ли призыв написать нам',2),(),RenderTemplate())


def test_emphasis_fragment_cannot_invent_or_duplicate_text(cinematic):
    script,_=cinematic
    for emphasis in (['рис'],['риск?','риск?']):
        value=script.editorial.to_dict();value['emphasis']=emphasis
        with pytest.raises(ValueError):parse_editorial(value,script.hook,script.voiceover)


def test_real_logo_overlay_filter_branch(tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('Run in Docker')
    from app.cinematic_media import overlay_inputs
    from app.render_subtitles import ass_header
    from app.video_renderer import run_media
    Image.new('RGB',(1080,1920),'#806040').save(tmp_path/'background.png')
    Image.new('RGB',(100,100),'#ee1111').save(tmp_path/'logo.png')
    (tmp_path/'subtitles.ass').write_text(ass_header(RenderTemplate()))
    graph=video_graph(2,(.65,.48,.2,.18),(.35,.3,.5,.45),logo=True).rstrip(';')
    inputs=['-loop','1','-i',str(tmp_path/'background.png'),'-f','lavfi','-i','anullsrc',
            '-f','lavfi','-i','anullsrc']+overlay_inputs(Path('assets/overlays'))+['-loop','1','-i',str(tmp_path/'logo.png')]
    run_media(['ffmpeg','-v','error','-filter_complex_threads','1']+inputs+
              ['-filter_complex',graph,'-map','[v]','-frames:v','1','-update','1',str(tmp_path/'frame.png')],cwd=tmp_path)
    with Image.open(tmp_path/'frame.png') as image:
        r,g,b=image.getpixel((120,330))[:3]
        assert r>180 and g<60 and b<60
