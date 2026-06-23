from dataclasses import dataclass

import pytest
from django.urls import reverse

from assistant.services import answer_question
from documents.tests.factories import make_article, make_document, make_redaction


@dataclass
class _Block:
    type: str
    text: str


class _FakeResp:
    def __init__(self, text):
        self.content = [_Block("text", text)]
        self.stop_reason = "end_turn"


class _Msgs:
    def __init__(self, capture):
        self.capture = capture

    def create(self, **kwargs):
        self.capture.append(kwargs)
        return _FakeResp("Ответ со ссылкой на Статья 127.")


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = _Msgs(self.calls)


@pytest.fixture
def published(db):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="127", title="Отпуск",
                 text="компенсация за неиспользованный отпуск при увольнении")
    red.publish()
    return doc


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("r", password="p12345678")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_history_prepended_before_grounded_current(published):
    fake = _FakeClient()
    history = [
        {"role": "user", "content": "первый вопрос"},
        {"role": "assistant", "content": "первый ответ"},
    ]
    answer_question("отпуск компенсация", history=history, client=fake)

    messages = fake.calls[0]["messages"]
    assert messages[0]["content"] == "первый вопрос"
    assert messages[1]["content"] == "первый ответ"
    # текущий вопрос — последним и заземлён статьями
    assert "Статьи из корпуса" in messages[-1]["content"]


@pytest.mark.django_db
def test_view_accumulates_conversation(auth_client, published, settings):
    settings.ANTHROPIC_API_KEY = ""  # retrieval-only — без сети
    auth_client.get(reverse("assistant"), {"q": "первый отпуск"})
    content = auth_client.get(reverse("assistant"), {"q": "второй отпуск"}).content.decode()
    assert "первый отпуск" in content
    assert "второй отпуск" in content


@pytest.mark.django_db
def test_reset_clears_conversation(auth_client, published, settings):
    settings.ANTHROPIC_API_KEY = ""
    auth_client.get(reverse("assistant"), {"q": "первый отпуск"})
    content = auth_client.get(reverse("assistant"), {"reset": "1"}).content.decode()
    assert "первый отпуск" not in content
