from datetime import date

import pytest
from django.urls import reverse

from documents.models import Link
from documents.tests.factories import make_article, make_document, make_link, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_list_requires_login(client):
    response = client.get(reverse("document_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_list_shows_only_documents_with_published_current_redaction(auth_client):
    published_doc = make_document(slug="published", official_number="1")
    red = make_redaction(published_doc, redaction_date=date(2024, 1, 1))
    red.publish()

    draft_doc = make_document(slug="draft-only", official_number="2")
    make_redaction(draft_doc, redaction_date=date(2024, 1, 1))  # остаётся черновиком

    response = auth_client.get(reverse("document_list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "published" in content or "№ 1" in content
    assert "draft-only" not in content


@pytest.mark.django_db
def test_detail_shows_requisites_articles_and_confirmed_links(auth_client):
    doc = make_document(slug="tk-rf", official_number="197-ФЗ")
    red = make_redaction(doc, redaction_date=date(2024, 1, 1))
    red.publish()
    make_article(red, number="81", title="Расторжение трудового договора")

    target = make_document(slug="other", official_number="125-ФЗ")
    make_link(
        from_document=doc,
        to_document=target,
        link_type=Link.LinkType.REFERENCES,
        status=Link.Status.CONFIRMED,
    )
    make_link(
        from_document=doc,
        to_document=target,
        link_type=Link.LinkType.AMENDS,
        status=Link.Status.SUGGESTED,  # не должна показываться читателю
    )

    response = auth_client.get(reverse("document_detail", args=["tk-rf"]))
    content = response.content.decode()
    assert response.status_code == 200
    assert "197-ФЗ" in content
    assert "Расторжение трудового договора" in content
    assert "st-81" in content  # якорь статьи
    assert "125-ФЗ" in content  # подтверждённая связь видна
    assert content.count("Ссылается на") >= 1
    assert "Изменяет" not in content  # предложенная связь скрыта


@pytest.mark.django_db
def test_detail_404_when_no_published_redaction(auth_client):
    doc = make_document(slug="draft-only", official_number="X")
    make_redaction(doc, redaction_date=date(2024, 1, 1))  # черновик
    response = auth_client.get(reverse("document_detail", args=["draft-only"]))
    assert response.status_code == 404


@pytest.fixture
def curator_client(client, django_user_model):
    user = django_user_model.objects.create_user(
        "curator", password="pass12345", is_staff=True
    )
    client.force_login(user)
    return user, client


@pytest.mark.django_db
def test_curator_sees_suggested_links(curator_client):
    _user, cclient = curator_client
    doc = make_document(slug="csee", official_number="197-ФЗ")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()
    target = make_document(slug="csee-t", official_number="125-ФЗ")
    make_link(
        from_document=doc, to_document=target,
        link_type=Link.LinkType.REFERENCES, status=Link.Status.SUGGESTED,
    )
    response = cclient.get(reverse("document_detail", args=["csee"]))
    content = response.content.decode()
    assert "125-ФЗ" in content
    assert "предложена" in content  # пометка статуса для куратора


@pytest.mark.django_db
def test_reader_does_not_see_suggested_links(auth_client):
    doc = make_document(slug="rsee", official_number="197-ФЗ")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()
    target = make_document(slug="rsee-t", official_number="125-ФЗ")
    make_link(
        from_document=doc, to_document=target,
        link_type=Link.LinkType.REFERENCES, status=Link.Status.SUGGESTED,
    )
    response = auth_client.get(reverse("document_detail", args=["rsee"]))
    content = response.content.decode()
    assert "125-ФЗ" not in content       # предложенная связь скрыта от читателя
    assert "предложена" not in content


@pytest.mark.django_db
def test_diff_shows_changed_article_lines(auth_client):
    doc = make_document(slug="diff-doc", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    make_article(old, number="1", title="Цели", text="Старый текст статьи.")
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    make_article(new, number="1", title="Цели", text="Новый текст статьи.")
    new.publish()  # становится текущей, old.is_current снимается

    response = auth_client.get(
        reverse("redaction_diff", args=["diff-doc", old.pk])
    )
    content = response.content.decode()
    assert response.status_code == 200
    # направление: старая → текущая
    assert "2023" in content and "2024" in content
    assert "Новый текст статьи." in content   # строка со знаком +
    assert "Старый текст статьи." in content  # строка со знаком −
    assert "изменена" in content


@pytest.mark.django_db
def test_diff_added_removed_and_same_articles(auth_client):
    doc = make_document(slug="diff-ars", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    make_article(old, number="1", title="Без изменений", text="Стабильный текст.", order=1)
    make_article(old, number="2", title="Будет удалена", text="Текст удаляемой.", order=2)
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    make_article(new, number="1", title="Без изменений", text="Стабильный текст.", order=1)
    make_article(new, number="3", title="Новая статья", text="Текст новой.", order=2)
    new.publish()

    response = auth_client.get(reverse("redaction_diff", args=["diff-ars", old.pk]))
    content = response.content.decode()
    assert "Статья 3" in content and "добавлена" in content
    assert "Статья 2" in content and "удалена" in content
    # неизменённая статья не показывается
    assert "Статья 1" not in content
    assert "Стабильный текст." not in content


@pytest.mark.django_db
def test_diff_no_changes_message(auth_client):
    doc = make_document(slug="diff-same", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    make_article(old, number="1", title="Цели", text="Тот же текст.")
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    make_article(new, number="1", title="Цели", text="Тот же текст.")
    new.publish()

    response = auth_client.get(reverse("redaction_diff", args=["diff-same", old.pk]))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Текстовых изменений между этими редакциями нет." in content
