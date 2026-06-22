# Поиск по тексту акта (search-within-document) — дизайн (2026-06-23)

Базовая возможность любой СПС (Гарант/Консультант «искать в документе»): на странице
акта найти статьи по слову, прыгнуть к ним. Независимо от трека AI (#47).

## Подход

Глобальный `search_documents` схлопывает результаты «один лучший хит на документ» — не
годится для «все статьи внутри ОДНОГО акта». Поэтому отдельная чистая функция, а не
перегрузка.

### `search/services.py` — `search_in_document(document, query_text, *, limit=50)`
- Переиспользует `_build_query` (та же лемматизация/синонимы) и `_snippets_by_pk`
  (двухфазная подсветка) — консистентно с глобальным поиском.
- Ищет ТОЛЬКО статьи текущей опубликованной редакции `document`, ранжирует по `ts_rank`.
- Возвращает `list[ArticleHit]` (новый dataclass): `anchor`, `label` («Статья N» /
  «Пункт N»), `title`, `snippet` (SafeString с `<mark>`), `rank`. Пустой запрос → [].

### `documents/views.py` — `document_search(request, slug)` (@login_required)
- get_object_or_404(Document, slug); текущая опубликованная редакция (как в document_detail).
- `q = request.GET.get("q","")`; `hits = search_in_document(...)` если q.
- Всегда рендерит частичку `documents/_find_results.html` (HTMX-эндпоинт).

### Маршрут и UI
- `config/urls.py`: `path("doc/<slug:slug>/find/", views.document_search, name="document_search")`.
- `document_detail.html`: компактная форма «Найти в этом акте» (input `q`,
  `hx-get` на find-route, `hx-trigger="keyup changed delay:400ms, search"`,
  `hx-target="#find-results"`), div `#find-results`. Hotspot трогаем минимально — один блок.
- `_find_results.html`: список хитов (deep-link `#<anchor>` → к статье в этой же странице),
  заголовок «N совпадений», пустые состояния («ничего», «введите запрос»).

## Тестирование
Изолированно: `search/tests/test_in_document.py` (django_db, реальный FTS) — находит статью
по слову/возвращает anchor+label+snippet; запрос мимо → []; пустой → []; чужой документ не
попадает (scope). `documents/tests/test_find_view.py` — login-gate; GET с q → партиал с
deep-link; без q → форма-партиал. Hotspot `test_views.py` не трогаем.

## Риск
Аддитивно: новая функция + новый view/route + один блок в reader-шаблоне. Ноль
моделей/миграций. Переиспользует существующий FTS. Обратимо.
