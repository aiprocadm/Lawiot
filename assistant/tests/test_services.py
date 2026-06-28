from dataclasses import dataclass

import pytest

from assistant.services import (
    MODE_NO_RESULTS,
    MODE_RETRIEVAL_ONLY,
    MODE_SYNTHESIZED,
    answer_question,
)
from documents.tests.factories import make_article, make_document, make_redaction


@dataclass
class _Block:
    type: str
    text: str


class _FakeResp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block("text", text)]
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def create(self, **kwargs):
        if self._exc:
            raise self._exc
        return self._resp


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self.messages = _FakeMessages(resp, exc)


@pytest.fixture
def published_doc(db):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="127", title="Отпуск",
                 text="компенсация за неиспользованный отпуск при увольнении")
    red.publish()
    return doc


@pytest.mark.django_db
def test_no_key_returns_retrieval_only(published_doc, settings):
    settings.ANTHROPIC_API_KEY = ""
    ans = answer_question("отпуск увольнение компенсация")
    assert ans.mode == MODE_RETRIEVAL_ONLY
    assert ans.answer_text is None
    assert ans.articles


@pytest.mark.django_db
def test_fake_client_synthesizes(published_doc):
    client = _FakeClient(resp=_FakeResp("Да, см. Статья 127."))
    ans = answer_question("отпуск увольнение компенсация", client=client)
    assert ans.mode == MODE_SYNTHESIZED
    assert "Статья 127" in ans.answer_text


@pytest.mark.django_db
def test_synthesized_flags_unverified_citation(published_doc):
    # Модель цитирует статью вне найденного набора (только ст.127) → флаг.
    client = _FakeClient(resp=_FakeResp("См. Статья 127, а также Статья 999."))
    ans = answer_question("отпуск увольнение компенсация", client=client)
    assert ans.mode == MODE_SYNTHESIZED
    assert ans.unverified_citations == ["999"]


@pytest.mark.django_db
def test_empty_synthesis_falls_back(published_doc):
    client = _FakeClient(resp=_FakeResp("   "))  # пустой текст (напр. max_tokens)
    ans = answer_question("отпуск увольнение компенсация", client=client)
    assert ans.mode == MODE_RETRIEVAL_ONLY
    assert ans.error == "empty"
    assert ans.articles


@pytest.mark.django_db
def test_api_error_falls_back(published_doc):
    client = _FakeClient(exc=RuntimeError("boom"))
    ans = answer_question("отпуск увольнение компенсация", client=client)
    assert ans.mode == MODE_RETRIEVAL_ONLY
    assert ans.error
    assert ans.articles


@pytest.mark.django_db
def test_api_error_logs_traceback(published_doc, caplog):
    import logging

    # Логгер "assistant" имеет propagate=False, поэтому handler caplog (на root)
    # его не видит — цепляем напрямую к нему.
    assistant_logger = logging.getLogger("assistant")
    assistant_logger.addHandler(caplog.handler)
    try:
        client = _FakeClient(exc=RuntimeError("boom"))
        with caplog.at_level(logging.WARNING, logger="assistant"):
            answer_question("отпуск увольнение компенсация", client=client)
    finally:
        assistant_logger.removeHandler(caplog.handler)

    failures = [r for r in caplog.records if "synthesis failed" in r.getMessage()]
    assert failures, "ожидали запись лога о сбое синтеза"
    assert failures[0].exc_info is not None, "лог сбоя API должен содержать трейсбэк"


@pytest.mark.django_db
def test_refusal_falls_back(published_doc):
    client = _FakeClient(resp=_FakeResp("", stop_reason="refusal"))
    ans = answer_question("отпуск увольнение компенсация", client=client)
    assert ans.mode == MODE_RETRIEVAL_ONLY
    assert ans.error == "refusal"


@pytest.mark.django_db
def test_no_results_when_corpus_has_nothing(settings):
    settings.ANTHROPIC_API_KEY = ""
    ans = answer_question("блокчейн криптовалюта майнинг")
    assert ans.mode == MODE_NO_RESULTS
    assert ans.articles == []
