"""Тесты стриминга ответа ассистента (AI-срез 2)."""

import pytest
from django.urls import reverse

from assistant.services import (
    MODE_NO_RESULTS,
    MODE_RETRIEVAL_ONLY,
    MODE_SYNTHESIZED,
    finalize_answer,
    stream_answer,
)
from assistant.views import SESSION_KEY
from documents.tests.factories import make_article, make_document, make_redaction


class _FakeStream:
    """Контекст-менеджер как у `client.messages.stream()`."""

    def __init__(self, deltas, exc=None):
        self._deltas = deltas
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        for d in self._deltas:
            yield d
        if self._exc:
            raise self._exc


class _FakeMessages:
    def __init__(self, deltas, exc=None):
        self._deltas = deltas
        self._exc = exc

    def stream(self, **kwargs):
        return _FakeStream(self._deltas, self._exc)


class _FakeStreamClient:
    def __init__(self, deltas, exc=None):
        self.messages = _FakeMessages(deltas, exc)


@pytest.fixture
def published_doc(db):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(
        red,
        number="127",
        title="Отпуск",
        text="компенсация за неиспользованный отпуск при увольнении",
    )
    red.publish()
    return doc


@pytest.mark.django_db
def test_stream_synthesizes_deltas(published_doc):
    client = _FakeStreamClient(deltas=["Да", ", см. ", "Статья 127."])
    articles, deltas = stream_answer("отпуск увольнение компенсация", client=client)
    assert articles  # статьи-основания готовы сразу
    text = "".join(deltas)
    assert text == "Да, см. Статья 127."


@pytest.mark.django_db
def test_stream_no_key_returns_no_deltas(published_doc, settings):
    settings.ANTHROPIC_API_KEY = ""
    articles, deltas = stream_answer("отпуск увольнение компенсация")
    assert articles
    assert list(deltas) == []


@pytest.mark.django_db
def test_stream_no_results_empty(published_doc):
    client = _FakeStreamClient(deltas=["неважно"])
    articles, deltas = stream_answer("закон о квантовой телепортации", client=client)
    assert articles == []
    assert list(deltas) == []


@pytest.mark.django_db
def test_stream_graceful_on_midstream_error(published_doc):
    client = _FakeStreamClient(deltas=["Часть ответа"], exc=RuntimeError("boom"))
    articles, deltas = stream_answer("отпуск увольнение компенсация", client=client)
    # Что успело стримнуться — сохраняется; исключение не пробрасывается.
    assert "".join(deltas) == "Часть ответа"


@pytest.mark.django_db
def test_finalize_synthesized(published_doc):
    articles, _ = stream_answer(
        "отпуск увольнение компенсация",
        client=_FakeStreamClient(deltas=[""]),
    )
    ans = finalize_answer("отпуск увольнение компенсация", articles, "Да, см. Статья 127.")
    assert ans.mode == MODE_SYNTHESIZED
    assert ans.answer_text == "Да, см. Статья 127."


@pytest.mark.django_db
def test_finalize_empty_text_is_retrieval_only(published_doc):
    articles, _ = stream_answer(
        "отпуск увольнение компенсация",
        client=_FakeStreamClient(deltas=[""]),
    )
    ans = finalize_answer("отпуск увольнение компенсация", articles, "")
    assert ans.mode == MODE_RETRIEVAL_ONLY
    assert ans.answer_text is None


@pytest.mark.django_db
def test_finalize_no_articles_is_no_results(published_doc):
    ans = finalize_answer("вопрос", [], "")
    assert ans.mode == MODE_NO_RESULTS


@pytest.mark.django_db
def test_finalize_flags_unverified_citation(published_doc):
    articles, _ = stream_answer(
        "отпуск увольнение компенсация",
        client=_FakeStreamClient(deltas=[""]),
    )
    ans = finalize_answer("отпуск увольнение компенсация", articles, "См. Статья 999.")
    assert "999" in ans.unverified_citations


# --- Вью стриминга -------------------------------------------------------


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return user, client


@pytest.mark.django_db
def test_assistant_stream_requires_login(client):
    resp = client.get(reverse("assistant_stream"), {"q": "отпуск"})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_assistant_stream_empty_question_yields_nothing(auth_client):
    _, client = auth_client
    resp = client.get(reverse("assistant_stream"))
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content) == b""


@pytest.mark.django_db
def test_assistant_stream_streams_deltas_and_persists_turn(auth_client, published_doc, monkeypatch):
    _, client = auth_client
    monkeypatch.setattr(
        "assistant.services._default_client",
        lambda: _FakeStreamClient(deltas=["Да", ", см. ", "Статья 127."]),
    )
    resp = client.get(reverse("assistant_stream"), {"q": "отпуск увольнение компенсация"})
    streamed = b"".join(resp.streaming_content).decode()
    assert streamed == "Да, см. Статья 127."

    # Ход персистнут в сессию финализатором генератора.
    convo = client.session[SESSION_KEY]
    assert len(convo) == 1
    assert convo[0]["mode"] == MODE_SYNTHESIZED
    assert convo[0]["a"] == "Да, см. Статья 127."
    assert convo[0]["articles"]


@pytest.mark.django_db
def test_assistant_stream_persists_partial_turn_on_disconnect(
    auth_client, published_doc, monkeypatch
):
    """Дисконнект клиента (закрытие генератора) всё равно персистит ход."""
    _, client = auth_client
    monkeypatch.setattr(
        "assistant.services._default_client",
        lambda: _FakeStreamClient(deltas=["Да", ", см. ", "Статья 127."]),
    )
    resp = client.get(reverse("assistant_stream"), {"q": "отпуск увольнение компенсация"})
    first = next(resp.streaming_content)  # получили часть ответа...
    resp._iterator.close()  # ...и «отключились»: GeneratorExit в тело → finally

    assert first == b"\xd0\x94\xd0\xb0"  # "Да" в utf-8
    convo = client.session[SESSION_KEY]
    assert len(convo) == 1
    assert convo[0]["a"] == "Да"  # ровно то, что успело стримнуться


@pytest.mark.django_db
def test_assistant_stream_retrieval_only_persists_without_text(
    auth_client, published_doc, settings
):
    _, client = auth_client
    settings.ANTHROPIC_API_KEY = ""  # нет клиента → нет дельт
    resp = client.get(reverse("assistant_stream"), {"q": "отпуск увольнение компенсация"})
    assert b"".join(resp.streaming_content) == b""
    convo = client.session[SESSION_KEY]
    assert len(convo) == 1
    assert convo[0]["mode"] == MODE_RETRIEVAL_ONLY
    assert convo[0]["a"] is None
    assert convo[0]["articles"]
