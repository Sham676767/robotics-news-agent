from pathlib import Path
import yaml


def test_background_workflow_limits_secret_scope_and_exports_only_backgrounds():
    data = yaml.safe_load(Path('.github/workflows/generate-backgrounds.yml').read_text())
    assert data['permissions'] == {'contents': 'read'}
    trigger = data.get('on', data.get(True))
    assert trigger['push']['branches'] == ['codex/backgrounds-20261102']
    job = data['jobs']['generate']
    assert job['timeout-minutes'] == 35
    steps = job['steps']
    secret_steps = [s for s in steps if 'OPENROUTER_API_KEY' in s.get('env', {})]
    assert len(secret_steps) == 1
    assert "generate_batch(provider,'document',6,yes=True)" in secret_steps[0]['run']
    upload = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact'))
    assert upload['with']['path'] == 'assets/backgrounds/document/'
    assert upload['if'] == 'always()'
    assert next(s for s in steps if s.get('uses', '').startswith('actions/checkout'))['with']['persist-credentials'] is False
