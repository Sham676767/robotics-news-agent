from dataclasses import replace

import pytest

from app.language_guard import validate_russian_draft


def test_accepts_russian_text_with_original_name(legal_package):
    draft, _ = legal_package
    section = replace(draft.sections[0], body="Учебный материал включает название Example Service и описание проверки.")
    validate_russian_draft(replace(draft, sections=(section,)))


def test_does_not_apply_daily_digest_rules(legal_package):
    draft, _ = legal_package
    validate_russian_draft(replace(draft, title="Материал для обсуждения на неделе"))


@pytest.mark.parametrize("field", ["title", "intro", "headline", "body"])
def test_rejects_non_russian_text_in_every_field(legal_package, field):
    draft, _ = legal_package
    if field in {"title", "intro"}:
        draft = replace(draft, **{field: "This is an English legal draft."})
    else:
        draft = replace(draft, sections=(replace(draft.sections[0], **{field: "English text for review."}),))
    with pytest.raises(ValueError, match="not sufficiently Russian"):
        validate_russian_draft(draft)
