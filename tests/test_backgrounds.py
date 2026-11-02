import base64
import io
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from app.backgrounds import ImageBackgroundProvider, LibraryBackgroundProvider, StubBackgroundProvider, generate_batch


@pytest.fixture
def image_data():
    buffer = io.BytesIO()
    Image.new('RGB', (1080, 1920), '#806040').save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


def test_unconfirmed_batch_never_calls_network_or_writes(tmp_path, monkeypatch):
    post = Mock(side_effect=AssertionError('No paid calls'))
    monkeypatch.setattr(httpx, 'post', post)
    provider = ImageBackgroundProvider(tmp_path/'library', 'secret', 'model', 'prompt')
    plan = generate_batch(provider, 'document', 6)
    assert plan['estimated_generations'] == 6 and plan['maximum_http_requests'] == 12
    assert plan['confirmation_required'] and not (tmp_path/'library').exists()
    post.assert_not_called()


@pytest.mark.parametrize('fallback', [False, True])
def test_generation_cache_and_metadata(tmp_path, monkeypatch, image_data, fallback):
    success = httpx.Response(200, json={'choices': [{'message': {'images': [{'image_url': {'url': 'data:image/png;base64,'+image_data}}]}}]}) if fallback else httpx.Response(200,json={'data':[{'b64_json':image_data}]})
    post=Mock(side_effect=([httpx.Response(404),success] if fallback else [success]))
    monkeypatch.setattr(httpx,'post',post)
    provider=ImageBackgroundProvider(tmp_path,'secret','model','prompt')
    first=generate_batch(provider,'document',1,yes=True)
    second=generate_batch(provider,'document',1)
    assert first['files']==second['files'] and second['cached']==1
    path=provider.destination('document',0)
    assert path.with_suffix('.json').is_file()
    assert 'secret' not in path.with_suffix('.json').read_text()
    assert post.call_count==(2 if fallback else 1)
    if fallback: assert post.call_args.kwargs['json']['modalities']==['image','text']


@pytest.mark.parametrize('status',[401,403,429,500])
def test_paid_errors_do_not_trigger_fallback_or_retry(tmp_path,monkeypatch,status):
    post=Mock(return_value=httpx.Response(status))
    monkeypatch.setattr(httpx,'post',post)
    with pytest.raises(ValueError,match='HTTP'):
        ImageBackgroundProvider(tmp_path,'secret','model','prompt').get('document')
    assert post.call_count==1


def test_invalid_dimensions_rejected(tmp_path,monkeypatch):
    buffer=io.BytesIO();Image.new('RGB',(100,100)).save(buffer,format='PNG')
    monkeypatch.setattr(httpx,'post',Mock(return_value=httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(buffer.getvalue()).decode()}]})))
    with pytest.raises(ValueError,match='1080'):
        ImageBackgroundProvider(tmp_path,'secret','model','prompt').get('document')
    assert not list(tmp_path.rglob('*.png'))


def test_library_rotation_and_stub_are_offline(tmp_path):
    folder=tmp_path/'document';folder.mkdir()
    for n in range(3):Image.new('RGB',(1080,1920)).save(folder/f'{n}.png')
    library=LibraryBackgroundProvider(tmp_path)
    assert library.get('document',variant=0).path != library.get('document',variant=1).path
    assert library.get('document',variant=0).path == library.get('document',variant=3).path
    stub=StubBackgroundProvider(tmp_path/'stub').get('document')
    with Image.open(stub.path) as image: assert image.size==(1080,1920)
    with pytest.raises(ValueError):library.get('../outside')
    with pytest.raises(ValueError):library.get('missing')


def test_checked_in_jpeg_exports_reuse_paid_cache_without_key_or_network(tmp_path,monkeypatch):
    import json,hashlib
    provider=ImageBackgroundProvider(tmp_path,'','model','prompt')
    folder=tmp_path/'document';folder.mkdir()
    image=folder/'office-01.jpg';Image.new('RGB',(1080,1920)).save(image)
    metadata={'original_file':provider.destination('document',0).name,'model':'model',
              'prompt':'prompt\nComposition variant: 1. Portrait 9:16, at least 1080x1920.',
              'sha256':hashlib.sha256(image.read_bytes()).hexdigest()}
    image.with_suffix('.json').write_text(json.dumps(metadata))
    monkeypatch.setattr(httpx,'post',Mock(side_effect=AssertionError('Must not regenerate existing paid image')))
    result=generate_batch(provider,'document',1)
    assert result['cached']==1 and result['estimated_generations']==0
    assert result['files']==[str(image)]


@pytest.mark.parametrize('names',[['../outside.png'],['one.jpg','one.jpg'],['missing.jpg']])
def test_library_manifest_rejects_unsafe_duplicate_or_missing_files(tmp_path,names):
    import json
    folder=tmp_path/'document';folder.mkdir()
    (folder/'one.jpg').write_bytes(b'fixture')
    (folder/'library.json').write_text(json.dumps({'files':names}))
    with pytest.raises(ValueError):LibraryBackgroundProvider(tmp_path).get('document')
