import pytest

from documents.models import Document, PendingAct, Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.mark.django_db
def test_is_resolved_false_without_matching_document():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz",
        title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    assert pa.is_resolved is False


@pytest.mark.django_db
def test_is_resolved_false_with_only_draft():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz",
        title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    doc = make_document(
        slug="zanyatost-565-fz", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.DRAFT, is_current=False)
    assert pa.is_resolved is False


@pytest.mark.django_db
def test_is_resolved_true_with_published_current():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz",
        title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    doc = make_document(
        slug="zanyatost-565-fz", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True)
    assert pa.is_resolved is True


@pytest.mark.django_db
def test_is_resolved_false_when_number_matches_but_doc_type_differs():
    pa = PendingAct.objects.create(
        slug="x-565", title="Иной акт", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    doc = make_document(
        slug="x-565-decree", official_number="565-ФЗ", doc_type=Document.DocType.DECREE,
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True)
    assert pa.is_resolved is False


@pytest.mark.django_db
def test_seed_corpus_materializes_pending_acts():
    from django.core.management import call_command

    call_command("seed_corpus")
    assert PendingAct.objects.filter(slug="zanyatost-565-fz").exists()


@pytest.mark.django_db
def test_seed_corpus_removes_resolved_pending_act():
    from django.core.management import call_command

    # 565-ФЗ "разрешён": заведён и опубликован
    doc = make_document(
        slug="zanyatost-565-fz", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
        title="О занятости населения в Российской Федерации",
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True)

    call_command("seed_corpus")

    # разрешённая запись не остаётся в реестре
    assert not PendingAct.objects.filter(slug="zanyatost-565-fz").exists()
