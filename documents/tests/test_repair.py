import pytest

from documents.models import compute_anchor
from documents.tests.factories import make_article


def test_compute_anchor_is_module_level_pure():
    assert compute_anchor("article", "123.20-1") == "st-123-20-1"
    assert compute_anchor("article", "341.1-1") == "st-341-1-1"
    assert compute_anchor("point", "1.1") == "p-1-1"
    assert compute_anchor("section", "I") == "razdel-i"


def test_compute_anchor_unknown_kind_raises():
    with pytest.raises(KeyError):
        compute_anchor("unknown", "1")


@pytest.mark.django_db
def test_save_still_derives_anchor_via_compute_anchor():
    art = make_article(number="123.20-1", title="Личный фонд", order=1)
    art.refresh_from_db()
    assert art.anchor == "st-123-20-1"
