import pytest

from documents.tests.factories import make_document
from ingestion.scheduling import iter_targets


@pytest.mark.django_db
def test_iter_targets_selects_only_flagged_docs_with_source_url():
    make_document(
        slug="a", official_number="1", auto_ingest=True, source_url="https://e.test/a"
    )
    make_document(  # flagged but no URL → excluded
        slug="b", official_number="2", auto_ingest=True, source_url=""
    )
    make_document(  # has URL but not flagged → excluded
        slug="c", official_number="3", auto_ingest=False, source_url="https://e.test/c"
    )
    targets = list(iter_targets())
    assert len(targets) == 1
    t = targets[0]
    assert t.document.slug == "a"
    assert t.url == "https://e.test/a"
    assert t.target_key == "a"  # конвенция target_key = slug (как у ingest_url)
