import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.draft_validation import validate_legal_draft
from app.legal_draft import build_legal_draft, load_legal_draft, save_legal_draft


def test_review_package_attaches_original_sources(legal_package):
    draft, sources = legal_package
    package = build_legal_draft(draft, sources)
    assert package["status"] == "review_required"
    assert package["sources"][0]["content"] == sources[0].content
    assert package["source_links"] == [{"section_index": 1, "source": sources[0].source, "url": sources[0].url}]


def test_save_load_roundtrip_and_reruns_do_not_overwrite(tmp_path, legal_package):
    draft, sources = legal_package
    first = save_legal_draft(draft, sources, tmp_path)
    original = first.read_bytes()
    second = save_legal_draft(draft, sources, tmp_path)
    assert first != second
    assert first.read_bytes() == original
    assert load_legal_draft(first) == (draft, sources)
    assert len(list(tmp_path.iterdir())) == 2


def test_invalid_draft_produces_no_output(tmp_path, legal_package):
    draft, sources = legal_package
    output_dir = tmp_path / "new-output"
    with pytest.raises(ValueError):
        save_legal_draft(replace(draft, title=""), sources, output_dir)
    assert not output_dir.exists()


def test_failed_write_leaves_no_partial_file(monkeypatch, tmp_path, legal_package):
    draft, sources = legal_package
    monkeypatch.setattr("app.legal_draft.os.replace", Mock(side_effect=OSError("write failed")))
    with pytest.raises(OSError):
        save_legal_draft(draft, sources, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("count", [1, 2, 6])
def test_no_five_story_quota(legal_package, count):
    draft, sources = legal_package
    validate_legal_draft(replace(draft, sections=draft.sections * count), sources)


@pytest.mark.parametrize("field", ["title", "intro"])
def test_required_draft_fields(legal_package, field):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="non-empty"):
        validate_legal_draft(replace(draft, **{field: " "}), sources)


@pytest.mark.parametrize("field", ["headline", "body"])
def test_required_section_fields(legal_package, field):
    draft, sources = legal_package
    section = replace(draft.sections[0], **{field: ""})
    with pytest.raises(ValueError, match="non-empty"):
        validate_legal_draft(replace(draft, sections=(section,)), sources)


@pytest.mark.parametrize("field", ["title", "source", "content", "url"])
def test_required_source_fields(legal_package, field):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="non-empty"):
        validate_legal_draft(draft, (replace(sources[0], **{field: ""}),))


@pytest.mark.parametrize("url", ["not-a-url", "file:///tmp/legal.txt", "https://", "https://example.com/has space", "https://user:password@example.com", "http://["])
def test_rejects_invalid_source_urls(legal_package, url):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="invalid URL"):
        validate_legal_draft(draft, (replace(sources[0], url=url),))


def test_rejects_foreign_jurisdiction(legal_package):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="jurisdiction"):
        validate_legal_draft(draft, (replace(sources[0], jurisdiction="US"),))


def test_rejects_duplicate_sources(legal_package):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="Duplicate"):
        validate_legal_draft(draft, sources * 2)


def test_sources_and_sections_cannot_be_empty(legal_package):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="source"):
        validate_legal_draft(draft, ())
    with pytest.raises(ValueError, match="section"):
        validate_legal_draft(replace(draft, sections=()), sources)


@pytest.mark.parametrize("source_index", [0, 2, True, "1"])
def test_invalid_section_binding(legal_package, source_index):
    draft, sources = legal_package
    section = replace(draft.sections[0], source_index=source_index)
    with pytest.raises(ValueError, match="source_index"):
        validate_legal_draft(replace(draft, sections=(section,)), sources)


@pytest.mark.parametrize("bad", [[], None, {"draft": [], "sources": []}, {"draft": {}, "sources": "wrong"}])
def test_loader_rejects_invalid_shapes(tmp_path, bad):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_legal_draft(path)


def test_loader_rejects_boolean_index(tmp_path):
    package = json.loads((Path(__file__).parent / "fixtures/legal_draft.json").read_text())
    package["draft"]["sections"][0]["source_index"] = True
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match="integer"):
        load_legal_draft(path)


def test_final_gate_rechecks_intro_facts_before_saving(tmp_path, legal_package):
    draft, sources = legal_package
    with pytest.raises(ValueError, match="numbers absent"):
        save_legal_draft(replace(draft, intro="В тексте есть 99 утверждений."), sources, tmp_path)
    assert not list(tmp_path.iterdir())
