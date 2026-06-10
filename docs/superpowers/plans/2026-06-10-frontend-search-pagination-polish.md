# Frontend: живой поиск, пагинация, чистка detail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Задействовать htmx для живого поиска, добавить пагинацию в список актов и поиск, ограничить поиск LIMIT-ом, и вынести логику отбора связей/иерархии статей из шаблонов в view.

**Architecture:** Server-side Django templates + Pico CSS + htmx (уже подключён в base.html). View отдаёт полную страницу или partial-фрагмент в зависимости от заголовка `HX-Request`; partial инклюдится в полную страницу для работы без JS. Поиск кэшируется срезом-LIMIT до материализации в Python.

**Tech Stack:** Django, PostgreSQL full-text search, htmx 2.0.2, Pico CSS, pytest.

**Окружение (Windows):** тесты — `py -m pytest`, линт — `ruff check` (см. [[lawiot-lint-scope]]). Бар `python` зависает — использовать `py`.

---

## Файловая структура

- `search/services.py` — добавить константу LIMIT и срезы (Task 1).
- `search/views.py` — пагинация + выбор partial по HX-Request (Task 2, 3).
- `templates/search/search.html` — htmx-атрибуты на форме, обёртка `#search-results` (Task 2, 3).
- `templates/search/_results.html` — **создать**: фрагмент результатов + пагинация (Task 2).
- `documents/views.py` — пагинация списка (Task 4), разбиение связей + дерево статей (Task 5, 6).
- `templates/documents/document_list.html` — обёртка `#doc-list` (Task 4).
- `templates/documents/_list_items.html` — **создать**: фрагмент списка + пагинация (Task 4).
- `templates/documents/document_detail.html` — связи из готовых списков, рекурсивная иерархия (Task 5, 6).
- `templates/documents/_toc_node.html`, `_article_node.html` — **создать**: рекурсивные узлы (Task 6).
- Тесты: `search/tests/test_views.py`, `search/tests/test_services.py`, `documents/tests/test_views.py`.

---

## Task 1: LIMIT в поиске

**Files:**
- Modify: `search/services.py`
- Test: `search/tests/test_services.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `search/tests/test_services.py` (в начало — импорты, если файла-импортов нет, свериться с существующими):

```python
import pytest

from documents.tests.factories import make_document, make_redaction
from search import services
from search.services import search_documents


@pytest.mark.django_db
def test_search_caps_hits_per_source(monkeypatch):
    monkeypatch.setattr(services, "_MAX_HITS_PER_SOURCE", 2)
    for i in range(3):
        doc = make_document(slug=f"cap-{i}", official_number=str(i), title=f"Акт {i}")
        make_redaction(doc, full_text="уникальноеслово").publish()

    results = search_documents("уникальноеслово")
    assert len(results) <= 2
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `py -m pytest search/tests/test_services.py::test_search_caps_hits_per_source -v`
Expected: FAIL — `AttributeError: module 'search.services' has no attribute '_MAX_HITS_PER_SOURCE'`.

- [ ] **Step 3: Минимальная реализация**

В `search/services.py` добавить константу рядом с маркерами подсветки:

```python
_MAX_HITS_PER_SOURCE = 100
```

И в `search_documents` обрезать оба queryset срезом **до** итерации. Заменить присваивание `redaction_hits = apply_doc_filters(...)` так, чтобы результат среза материализовался:

```python
    redaction_hits = apply_doc_filters(
        Redaction.objects.filter(
            is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .annotate(snippet=_headline("full_text", query))
        .select_related("document"),
        "document__",
    ).order_by("-rank")[:_MAX_HITS_PER_SOURCE]

    article_hits = apply_doc_filters(
        Article.objects.filter(
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .annotate(snippet=_headline("text", query))
        .select_related("redaction__document"),
        "redaction__document__",
    ).order_by("-rank")[:_MAX_HITS_PER_SOURCE]
```

(`.order_by("-rank")` перед срезом гарантирует, что LIMIT берёт топ по релевантности, а не произвольные строки.)

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `py -m pytest search/tests/test_services.py -v`
Expected: PASS (новый тест и существующие).

- [ ] **Step 5: Commit**

```bash
git add search/services.py search/tests/test_services.py
git commit -m "perf(search): cap hits per source with SQL LIMIT before Python merge"
```

---

## Task 2: Пагинация поиска + partial (без htmx)

**Files:**
- Modify: `search/views.py`
- Create: `templates/search/_results.html`
- Modify: `templates/search/search.html`
- Test: `search/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `search/tests/test_views.py`:

```python
from search import views as search_views


@pytest.mark.django_db
def test_search_paginates_results(auth_client, monkeypatch):
    monkeypatch.setattr(search_views, "PAGE_SIZE", 2)
    for i in range(3):
        doc = make_document(slug=f"pg-{i}", official_number=str(i), title=f"Акт {i}")
        make_redaction(doc, full_text="пагинацияслово").publish()

    page1 = auth_client.get(reverse("search"), {"q": "пагинацияслово"})
    assert page1.context["page_obj"].paginator.count == 3
    assert len(page1.context["page_obj"].object_list) == 2
    assert page1.context["page_obj"].has_next is True

    page2 = auth_client.get(reverse("search"), {"q": "пагинацияслово", "page": "2"})
    assert len(page2.context["page_obj"].object_list) == 1
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `py -m pytest search/tests/test_views.py::test_search_paginates_results -v`
Expected: FAIL — `KeyError: 'page_obj'` (view ещё кладёт `results`).

- [ ] **Step 3: Реализация view**

Заменить содержимое `search/views.py` целиком:

```python
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from search.forms import SearchForm
from search.services import search_documents

PAGE_SIZE = 20


@login_required
def search_view(request):
    form = SearchForm(request.GET or None)
    results = []
    query = request.GET.get("q", "")
    if form.is_valid() and form.cleaned_data.get("q"):
        cd = form.cleaned_data
        results = search_documents(
            cd["q"],
            doc_type=cd["doc_type"],
            status=cd["status"],
            issuing_body=cd["issuing_body"],
            date_from=cd["date_from"],
            date_to=cd["date_to"],
        )

    page_obj = Paginator(results, PAGE_SIZE).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "form": form,
        "page_obj": page_obj,
        "query": query,
        "base_qs": params.urlencode(),
    }

    template = (
        "search/_results.html"
        if request.headers.get("HX-Request")
        else "search/search.html"
    )
    return render(request, template, context)
```

- [ ] **Step 4: Создать partial `templates/search/_results.html`**

```html
{% if query %}
<p>Найдено: {{ page_obj.paginator.count }} по запросу «{{ query }}».</p>
{% for r in page_obj %}
<article>
  <h3>
    <a href="{% url 'document_detail' r.document.slug %}{% if r.article_anchor %}#{{ r.article_anchor }}{% endif %}">
      {{ r.document.title }}{% if r.article_label %} — {{ r.article_label }}{% endif %}
    </a>
  </h3>
  <small>{{ r.document.get_doc_type_display }} № {{ r.document.official_number }} · {{ r.document.get_status_display }}</small>
  <p>{{ r.snippet }}</p>
</article>
{% empty %}
<p>Ничего не найдено.</p>
{% endfor %}

{% if page_obj.has_other_pages %}
<nav aria-label="Страницы результатов">
  {% if page_obj.has_previous %}
  <a href="?{{ base_qs }}&page={{ page_obj.previous_page_number }}"
     hx-get="?{{ base_qs }}&page={{ page_obj.previous_page_number }}"
     hx-target="#search-results" hx-push-url="true">← Назад</a>
  {% endif %}
  <span>Стр. {{ page_obj.number }} из {{ page_obj.paginator.num_pages }}</span>
  {% if page_obj.has_next %}
  <a href="?{{ base_qs }}&page={{ page_obj.next_page_number }}"
     hx-get="?{{ base_qs }}&page={{ page_obj.next_page_number }}"
     hx-target="#search-results" hx-push-url="true">Вперёд →</a>
  {% endif %}
</nav>
{% endif %}
{% endif %}
```

(`{{ r.snippet }}` без `|safe` — это уже `SafeString` из `_safe_snippet`; htmx-атрибуты на ссылках пагинации заработают в Task 3, без JS остаются обычными ссылками.)

- [ ] **Step 5: Обновить `templates/search/search.html`**

Заменить блок результатов на обёртку с include. Полностью:

```html
{% extends "base.html" %}
{% block title %}Поиск — Lawiot{% endblock %}
{% block content %}
<h1>Поиск по актам</h1>

<form method="get" role="search">
  <input type="search" name="q" value="{{ query }}" placeholder="Введите запрос…" aria-label="Запрос">
  <details>
    <summary>Фильтры</summary>
    <div class="grid">
      <label>Тип {{ form.doc_type }}</label>
      <label>Статус {{ form.status }}</label>
      <label>Орган {{ form.issuing_body }}</label>
    </div>
    <div class="grid">
      <label>Дата с {{ form.date_from }}</label>
      <label>Дата по {{ form.date_to }}</label>
    </div>
  </details>
  <button type="submit">Найти</button>
</form>

<div id="search-results">
  {% include "search/_results.html" %}
</div>
{% endblock %}
```

- [ ] **Step 6: Запустить тесты — убедиться, что проходят**

Run: `py -m pytest search/tests/ -v`
Expected: PASS (новый тест пагинации + существующие `test_search_*`).

- [ ] **Step 7: Commit**

```bash
git add search/views.py templates/search/_results.html templates/search/search.html search/tests/test_views.py
git commit -m "feat(search): paginate results and extract partial template"
```

---

## Task 3: htmx живой поиск

**Files:**
- Modify: `templates/search/search.html`
- Test: `search/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест (HX-Request → partial)**

Добавить в `search/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_search_hx_request_returns_partial(auth_client):
    doc = make_document(slug="hx", title="HX-Акт", official_number="1")
    make_redaction(doc, full_text="живойпоиск").publish()

    response = auth_client.get(
        reverse("search"), {"q": "живойпоиск"}, HTTP_HX_REQUEST="true"
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "HX-Акт" in content
    assert "<!doctype html" not in content.lower()  # без полной обвязки
    assert "<nav>" not in content                    # без верхней навигации base.html
```

- [ ] **Step 2: Запустить тест**

Run: `py -m pytest search/tests/test_views.py::test_search_hx_request_returns_partial -v`
Expected: PASS уже сейчас — выбор partial по HX-Request реализован в Task 2. Если PASS, тест валиден; переходим к навешиванию htmx-атрибутов на форму (визуальная часть, тестируется отдельно ниже). Если FAIL — проверить, что view из Task 2 применён.

- [ ] **Step 3: Навесить htmx-атрибуты на форму поиска**

В `templates/search/search.html` заменить открывающий тег формы:

```html
<form method="get" role="search"
      hx-get="{% url 'search' %}"
      hx-trigger="keyup changed delay:300ms from:input[name='q'], change, search"
      hx-target="#search-results"
      hx-push-url="true">
```

- [ ] **Step 4: Тест навешивания атрибутов**

Добавить в `search/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_search_form_has_htmx_attrs(auth_client):
    response = auth_client.get(reverse("search"))
    content = response.content.decode()
    assert 'hx-get=' in content
    assert 'hx-target="#search-results"' in content
    assert 'delay:300ms' in content
```

- [ ] **Step 5: Запустить тесты**

Run: `py -m pytest search/tests/test_views.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/search/search.html search/tests/test_views.py
git commit -m "feat(search): live htmx search with debounced input and filters"
```

---

## Task 4: Пагинация списка актов + htmx

**Files:**
- Modify: `documents/views.py`
- Create: `templates/documents/_list_items.html`
- Modify: `templates/documents/document_list.html`
- Test: `documents/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_views.py`:

```python
from documents import views as doc_views


@pytest.mark.django_db
def test_list_paginates(auth_client, monkeypatch):
    monkeypatch.setattr(doc_views, "PAGE_SIZE", 2)
    for i in range(3):
        d = make_document(slug=f"p-{i}", official_number=str(i), title=f"Акт {i}")
        make_redaction(d, redaction_date=date(2024, 1, 1)).publish()

    page1 = auth_client.get(reverse("document_list"))
    assert page1.context["page_obj"].paginator.count == 3
    assert len(page1.context["page_obj"].object_list) == 2

    page2 = auth_client.get(reverse("document_list"), {"page": "2"})
    assert len(page2.context["page_obj"].object_list) == 1


@pytest.mark.django_db
def test_list_hx_request_returns_partial(auth_client):
    d = make_document(slug="hxl", official_number="1", title="HX-Список-Акт")
    make_redaction(d, redaction_date=date(2024, 1, 1)).publish()
    response = auth_client.get(reverse("document_list"), HTTP_HX_REQUEST="true")
    content = response.content.decode()
    assert "HX-Список-Акт" in content
    assert "<!doctype html" not in content.lower()
```

- [ ] **Step 2: Запустить тест**

Run: `py -m pytest documents/tests/test_views.py::test_list_paginates -v`
Expected: FAIL — `KeyError: 'page_obj'`.

- [ ] **Step 3: Реализация view**

В `documents/views.py` добавить импорт и константу, заменить `document_list`:

```python
from django.core.paginator import Paginator
```

```python
PAGE_SIZE = 20


@login_required
def document_list(request):
    current = Redaction.objects.filter(
        document=OuterRef("pk"),
        is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    documents = Document.objects.filter(Exists(current)).order_by("title")
    page_obj = Paginator(documents, PAGE_SIZE).get_page(request.GET.get("page"))

    template = (
        "documents/_list_items.html"
        if request.headers.get("HX-Request")
        else "documents/document_list.html"
    )
    return render(request, template, {"page_obj": page_obj})
```

- [ ] **Step 4: Создать `templates/documents/_list_items.html`**

```html
<ul>
  {% for doc in page_obj %}
  <li>
    <a href="{% url 'document_detail' doc.slug %}">{{ doc.title }}</a>
    <small>({{ doc.get_doc_type_display }} № {{ doc.official_number }})</small>
  </li>
  {% empty %}
  <li>Опубликованных актов пока нет.</li>
  {% endfor %}
</ul>

{% if page_obj.has_other_pages %}
<nav aria-label="Страницы">
  {% if page_obj.has_previous %}
  <a href="?page={{ page_obj.previous_page_number }}"
     hx-get="?page={{ page_obj.previous_page_number }}"
     hx-target="#doc-list" hx-push-url="true">← Назад</a>
  {% endif %}
  <span>Стр. {{ page_obj.number }} из {{ page_obj.paginator.num_pages }}</span>
  {% if page_obj.has_next %}
  <a href="?page={{ page_obj.next_page_number }}"
     hx-get="?page={{ page_obj.next_page_number }}"
     hx-target="#doc-list" hx-push-url="true">Вперёд →</a>
  {% endif %}
</nav>
{% endif %}
```

- [ ] **Step 5: Обновить `templates/documents/document_list.html`**

```html
{% extends "base.html" %}
{% block title %}Акты — Lawiot{% endblock %}
{% block content %}
<h1>Нормативно-правовые акты</h1>
<div id="doc-list">
  {% include "documents/_list_items.html" %}
</div>
{% endblock %}
```

- [ ] **Step 6: Запустить тесты**

Run: `py -m pytest documents/tests/test_views.py -v`
Expected: PASS (новые + существующие list-тесты).

- [ ] **Step 7: Commit**

```bash
git add documents/views.py templates/documents/_list_items.html templates/documents/document_list.html documents/tests/test_views.py
git commit -m "feat(documents): paginate document list with htmx page navigation"
```

---

## Task 5: Разбиение связей detail в view

**Files:**
- Modify: `documents/views.py`
- Modify: `templates/documents/document_detail.html`
- Test: `documents/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_detail_splits_amendments_and_references(auth_client):
    doc = make_document(slug="split", official_number="197-ФЗ")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()
    target = make_document(slug="split-t", official_number="125-ФЗ")
    make_link(from_document=doc, to_document=target,
              link_type=Link.LinkType.AMENDS, status=Link.Status.CONFIRMED)
    make_link(from_document=doc, to_document=target,
              link_type=Link.LinkType.REFERENCES, status=Link.Status.CONFIRMED)

    response = auth_client.get(reverse("document_detail", args=["split"]))
    amendments = response.context["amendments"]
    references = response.context["references"]
    assert all(l.link_type in ("amends", "amended_by") for l in amendments)
    assert all(l.link_type == "references" for l in references)
    assert len(amendments) == 1
    assert len(references) == 1
```

- [ ] **Step 2: Запустить тест**

Run: `py -m pytest documents/tests/test_views.py::test_detail_splits_amendments_and_references -v`
Expected: FAIL — `KeyError: 'amendments'`.

- [ ] **Step 3: Реализация view**

В `documents/views.py`, в `document_detail`, заменить блок `outgoing = ...` и контекст. После вычисления `outgoing` (queryset уже фильтрован по `visible_statuses`) добавить разбиение и убрать `outgoing` из контекста:

```python
    outgoing = document.outgoing_links.filter(
        status__in=visible_statuses
    ).select_related("to_document")
    amendments = [
        link for link in outgoing
        if link.link_type in (Link.LinkType.AMENDS, Link.LinkType.AMENDED_BY)
    ]
    references = [
        link for link in outgoing if link.link_type == Link.LinkType.REFERENCES
    ]
```

В словаре контекста заменить `"outgoing": outgoing,` на:

```python
            "amendments": amendments,
            "references": references,
```

- [ ] **Step 4: Обновить aside в `templates/documents/document_detail.html`**

Заменить весь блок `<aside>...</aside>` (строки с двойным обходом `outgoing`) на:

```html
  <aside>
    <h3>Изменяющие / изменённые акты</h3>
    <ul>
      {% for link in amendments %}
      <li>{{ link.get_link_type_display }}:
        {% if link.to_document %}
        <a href="{% url 'document_detail' link.to_document.slug %}">{{ link.to_document.official_number }}</a>
        {% else %}{{ link.raw_citation }}{% endif %}{% if link.status == "suggested" %} <small>(предложена)</small>{% endif %}
      </li>
      {% endfor %}
    </ul>

    <h3>Ссылается на</h3>
    <ul>
      {% for link in references %}
      <li>Ссылается на:
        {% if link.to_document %}
        <a href="{% url 'document_detail' link.to_document.slug %}">{{ link.to_document.official_number }}</a>
        {% else %}<span>{{ link.raw_citation }} (вне корпуса)</span>{% endif %}{% if link.status == "suggested" %} <small>(предложена)</small>{% endif %}
      </li>
      {% endfor %}
    </ul>

    <h3>На него ссылаются</h3>
    <ul>
      {% for link in incoming %}
      <li><a href="{% url 'document_detail' link.from_document.slug %}">{{ link.from_document.official_number }}</a>{% if link.status == "suggested" %} <small>(предложена)</small>{% endif %}</li>
      {% endfor %}
    </ul>
  </aside>
```

- [ ] **Step 5: Запустить тесты**

Run: `py -m pytest documents/tests/test_views.py -v`
Expected: PASS (новый + существующие detail-тесты, включая `test_detail_shows_requisites_articles_and_confirmed_links`, `test_curator_sees_suggested_links`, `test_reader_does_not_see_suggested_links`).

- [ ] **Step 6: Commit**

```bash
git add documents/views.py templates/documents/document_detail.html documents/tests/test_views.py
git commit -m "refactor(documents): split link types in view instead of template"
```

---

## Task 6: Иерархия статей

**Files:**
- Modify: `documents/views.py`
- Create: `templates/documents/_toc_node.html`
- Create: `templates/documents/_article_node.html`
- Modify: `templates/documents/document_detail.html`
- Test: `documents/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_views.py`:

```python
from documents.models import Article


@pytest.mark.django_db
def test_detail_renders_article_hierarchy(auth_client):
    doc = make_document(slug="hier", official_number="197-ФЗ")
    red = make_redaction(doc, redaction_date=date(2024, 1, 1))
    red.publish()
    chapter = make_article(
        red, kind=Article.Kind.CHAPTER, number="1",
        title="Общие положения", text="", order=1,
    )
    make_article(
        red, kind=Article.Kind.ARTICLE, number="1",
        title="Цели", text="Текст статьи.", order=2, parent=chapter,
    )

    response = auth_client.get(reverse("document_detail", args=["hier"]))
    roots = response.context["article_tree"]
    assert len(roots) == 1                       # одна глава-корень
    assert roots[0].kind == "chapter"
    assert len(roots[0].child_nodes) == 1        # одна вложенная статья
    content = response.content.decode()
    assert "Общие положения" in content
    assert "Цели" in content
    assert "st-1" in content                     # якорь вложенной статьи


@pytest.mark.django_db
def test_detail_falls_back_to_full_text_without_articles(auth_client):
    doc = make_document(slug="plain", official_number="X")
    make_redaction(
        doc, redaction_date=date(2024, 1, 1), full_text="Сплошной текст акта."
    ).publish()
    response = auth_client.get(reverse("document_detail", args=["plain"]))
    assert response.context["article_tree"] == []
    assert "Сплошной текст акта." in response.content.decode()
```

- [ ] **Step 2: Запустить тест**

Run: `py -m pytest documents/tests/test_views.py::test_detail_renders_article_hierarchy -v`
Expected: FAIL — `KeyError: 'article_tree'`.

- [ ] **Step 3: Реализация дерева в view**

В `documents/views.py` добавить импорт в начало файла:

```python
from collections import defaultdict
```

В `document_detail` заменить строку `articles = redaction.articles.select_related("parent").all()` на построение дерева:

```python
    articles = list(redaction.articles.all())
    children_map = defaultdict(list)
    for a in articles:
        children_map[a.parent_id].append(a)
    for a in articles:
        a.child_nodes = children_map[a.id]
    article_tree = children_map[None]
```

В словаре контекста заменить `"articles": articles,` на:

```python
            "article_tree": article_tree,
```

(`children_map[None]` — корни; порядок сохраняется, т.к. `articles` отсортирован по `Meta.ordering = ["order"]`. `child_nodes` — атрибут на инстансе для рекурсивного шаблона.)

- [ ] **Step 4: Создать `templates/documents/_toc_node.html`**

```html
<li>
  <a href="#{{ node.anchor }}">{{ node.get_kind_display }} {{ node.number }}. {{ node.title }}</a>
  {% if node.child_nodes %}
  <ul>
    {% for child in node.child_nodes %}{% include "documents/_toc_node.html" with node=child %}{% endfor %}
  </ul>
  {% endif %}
</li>
```

- [ ] **Step 5: Создать `templates/documents/_article_node.html`**

```html
<section id="{{ node.anchor }}">
  <h3>{{ node.get_kind_display }} {{ node.number }}. {{ node.title }}</h3>
  {% if node.text %}<p>{{ node.text|linebreaks }}</p>{% endif %}
  {% for child in node.child_nodes %}{% include "documents/_article_node.html" with node=child %}{% endfor %}
</section>
```

- [ ] **Step 6: Обновить основной блок `templates/documents/document_detail.html`**

Заменить блок `<section>` с оглавлением/текстом (внутри `<div class="grid">`, до `<aside>`) на:

```html
  <section>
    {% if article_tree %}
    <h2>Оглавление</h2>
    <ul>
      {% for node in article_tree %}{% include "documents/_toc_node.html" with node=node %}{% endfor %}
    </ul>

    <h2>Текст</h2>
    {% for node in article_tree %}{% include "documents/_article_node.html" with node=node %}{% endfor %}
    {% else %}
    <h2>Текст</h2>
    <p>{{ redaction.full_text|linebreaks }}</p>
    {% endif %}
  </section>
```

- [ ] **Step 7: Запустить тесты**

Run: `py -m pytest documents/tests/test_views.py -v`
Expected: PASS (новые иерархия/фолбэк + существующие, включая `test_detail_shows_requisites_articles_and_confirmed_links` с якорем `st-81`).

- [ ] **Step 8: Commit**

```bash
git add documents/views.py templates/documents/_toc_node.html templates/documents/_article_node.html templates/documents/document_detail.html documents/tests/test_views.py
git commit -m "feat(documents): render nested article hierarchy in detail view"
```

---

## Финальная проверка (после всех задач)

- [ ] **Прогнать весь репозиторий** (см. [[lawiot-lint-scope]]):

Run: `ruff check`
Expected: без ошибок.

Run: `py -m pytest`
Expected: все тесты зелёные.

- [ ] **Ручная проверка smoke** (опционально, если доступна БД с данными): открыть `/`, `/search/?q=...`, `/doc/<slug>/` — проверить пагинацию, живой поиск, иерархию.

---

## Чеклист покрытия спеки

- Компонент 1 (пагинация списка) → Task 4.
- Компонент 2 (живой поиск + пагинация результатов) → Task 2 + Task 3.
- Компонент 3 (LIMIT) → Task 1.
- Компонент 4 (связи в view) → Task 5.
- Компонент 5 (иерархия статей) → Task 6.
- Тестирование (пагинация, HX-Request, LIMIT, связи, иерархия, фолбэк, lint scope) → тесты в каждой задаче + финальная проверка.
