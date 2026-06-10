# Frontend: живой поиск, пагинация и чистка detail

Дата: 2026-06-10
Статус: согласовано

## Цель

Улучшить логику фронтенда Lawiot (Django server-side templates + Pico CSS + htmx):
устранить проблемы масштабируемости (нет пагинации, поиск грузит весь корпус в
память), задействовать уже подключённый, но мёртвый htmx, и убрать логику отбора
из шаблонов в view. Соответствует предпочтению «простые, низкоподдерживаемые
решения».

## Контекст

- Фронтенд — серверные Django-шаблоны. Отдельного JS нет.
- `base.html` грузит Pico CSS и htmx 2.0.2 с CDN; htmx нигде не используется.
- `document_list` рендерит все опубликованные акты в один `<ul>` без пагинации.
- `search_documents` (search/services.py) загружает **все** совпавшие редакции и
  статьи в Python, дедуплицирует по документу, сортирует по рангу — без `LIMIT`.
- `document_detail.html` дважды обходит queryset `outgoing` с
  `{% if link.link_type == ... %}` — логика отбора в шаблоне.
- `Article` имеет три уровня иерархии (Раздел → Глава → Статья) через self-FK
  `parent`, сортировка по `order`, но шаблон рендерит плоский список.

## Объём (согласовано)

Поиск + пагинация + чистка detail (компоненты 1–5 ниже).

## Дизайн

### Компонент 1 — Пагинация списка актов

- `document_list` (documents/views.py): `Paginator`, 20 на страницу, `?page=N`.
- Явный `.order_by("title")` для детерминированного порядка (модель уже имеет
  `Meta.ordering = ["title"]`, но queryset с `Exists` — закрепляем явно).
- Список выносится в partial `templates/documents/_list_items.html`.
- Ссылки страниц: `hx-get` → `hx-target="#doc-list"`, `hx-push-url="true"`, с
  фолбэком на обычные `href="?page=N"` (работает без JS).
- View отдаёт partial при `HX-Request`, иначе полную страницу.

### Компонент 2 — Живой поиск + пагинация результатов

- Инпут поиска: `hx-get` на `search_view`,
  `hx-trigger="keyup changed delay:300ms, search"`,
  `hx-target="#search-results"`, `hx-push-url="true"`.
- Поля фильтров (`<details>`) триггерят тот же запрос по `change`.
- View детектит `request.headers.get("HX-Request")` → рендерит partial
  `templates/search/_results.html`; полная `search.html` инклюдит тот же partial
  для первичной загрузки и работы без JS.
- Результаты пагинируются `Paginator`, 20 на страницу; ссылки страниц — `hx-get`
  на `#search-results` с фолбэком на `?q=...&page=N`.

### Компонент 3 — LIMIT в поиске

- В `search_documents` каждый queryset (`redaction_hits`, `article_hits`)
  обрезается срезом `[:100]` (→ SQL `LIMIT 100`) **до** материализации.
- Существующий merge/dedup/sort по рангу в Python сохраняется; худший случай
  ограничен ~200 строками вместо всего корпуса.
- Константа лимита вынесена в модуль (например `_MAX_HITS_PER_SOURCE = 100`).

### Компонент 4 — Чистка detail: связи в view

- `document_detail` разбивает `outgoing` на два queryset:
  - `amendments` — `link_type in (amends, amended_by)`;
  - `references` — `link_type == references`.
- Видимость по статусу (CONFIRMED + SUGGESTED для staff) сохраняется.
- Шаблон итерирует готовые списки без `{% if link.link_type == ... %}`.

### Компонент 5 — Иерархия статей

- View строит дерево: корни — `parent_id is None`; children группируются по
  `parent_id` в Python из уже загруженного `articles` (без дополнительных
  запросов). Порядок — по `order`.
- Оглавление и текст рендерятся вложенно через рекурсивный partial
  `templates/documents/_article_node.html` (`{% include %}` сам в себя).
- Фолбэк на `redaction.full_text` сохраняется, если статей нет.

## Тестирование

- Пагинация: границы страниц, число элементов на странице; невалидный/выходящий
  за пределы `page` обрабатывается `Paginator.get_page` (клампит к 1/последней,
  не падает).
- htmx: `HX-Request` → partial (без `<html>`/nav), обычный запрос → полная
  страница.
- LIMIT: при > N совпадений в источнике берётся не более N строк.
- Связи: `amendments` и `references` содержат правильные типы; SUGGESTED видны
  только staff.
- Иерархия: дерево собрано корректно (корни/потомки/порядок), фолбэк на
  `full_text` при отсутствии статей.
- Lawiot lint scope: весь репозиторий — `ruff` (без путей) + `pytest`.

## Вне объёма

- Вендоринг CDN-ассетов / SRI-хэши (отдельная задача).
- Переключение редакций в detail (отдельная задача).
- i18n / `{% trans %}`.
