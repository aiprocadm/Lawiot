import pytest
from django.urls import reverse

from assistant.retrieval import retrieve
from assistant.services import MODE_RETRIEVAL_ONLY, answer_question
from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def two_acts(db):
    tk = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    tred = make_redaction(tk, full_text="")
    make_article(tred, number="127", title="Отпуск",
                 text="компенсация за неиспользованный отпуск при увольнении")
    tred.publish()
    other = make_document(slug="other", title="Другой акт", official_number="1")
    ored = make_redaction(other, full_text="")
    make_article(ored, number="5", title="Чужая",
                 text="компенсация за неиспользованный отпуск в другом акте")
    ored.publish()
    return tk, other


@pytest.fixture
def auth_client(client, django_user_model):
    u = django_user_model.objects.create_user("r", password="p12345678")
    u and client.force_login(u)
    return client


@pytest.mark.django_db
def test_scoped_retrieve_limits_to_document(two_acts):
    tk, _ = two_acts
    arts = retrieve("компенсация отпуск", document=tk)
    assert arts
    assert all(a.url.startswith("/doc/tk/") for a in arts)
    assert all(a.document_title == "ТК" for a in arts)


@pytest.mark.django_db
def test_scoped_answer_retrieval_only(two_acts, settings):
    settings.ANTHROPIC_API_KEY = ""
    tk, _ = two_acts
    ans = answer_question("компенсация отпуск", document=tk)
    assert ans.mode == MODE_RETRIEVAL_ONLY
    assert ans.articles
    assert all("/doc/tk/" in a.url for a in ans.articles)


@pytest.mark.django_db
def test_assistant_view_scoped_by_doc(auth_client, two_acts, settings):
    settings.ANTHROPIC_API_KEY = ""
    resp = auth_client.get(reverse("assistant"), {"q": "компенсация отпуск", "doc": "tk"})
    content = resp.content.decode()
    assert resp.status_code == 200
    assert "Вопрос по акту" in content
    assert "/doc/tk/#st-127" in content
    assert "/doc/other/" not in content  # чужой акт исключён областью


@pytest.mark.django_db
def test_assistant_view_unknown_doc_404(auth_client):
    resp = auth_client.get(reverse("assistant"), {"q": "x", "doc": "nope"})
    assert resp.status_code == 404
