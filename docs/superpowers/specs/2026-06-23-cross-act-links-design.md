# Межактовые гиперссылки в тексте — дизайн (2026-06-23)

Расширение #49 (внутри-документные ссылки) на МЕЖАКТОВЫЕ: упоминания «N-ФЗ» и кодексов
по имени («Трудовым кодексом») в тексте статьи → ссылка на страницу того акта в корпусе.
Ключевая возможность СПС (перекрёстные гиперссылки между документами). Разблокировано
мержем #49 (refs.py/_article_node.html на main).

## Подход (высокоточный, только-в-корпусе)

Линкуем ТОЛЬКО на акты, которые ЕСТЬ в корпусе (текущая опубл. редакция). Переиспользуем
проверенные паттерны цитат из `ingestion/links.py` (`CITATION_RE` для «NNN-ФЗ/ФКЗ`,
`CODEX_PATTERNS` для кодексов по склонениям). Нерезолвленные цитаты остаются текстом.

### `documents/refs.py`
- `build_corpus_links(exclude_slug=None) -> dict` — резолвер из корпуса (lazy-import
  `CODEX_PATTERNS` внутри функции — documents→ingestion только в рантайме, без цикла):
  `{"numbers": {official_number: url}, "codices": [(regex, url)]}`; исключает текущий акт
  (self-link не нужен). URL через `reverse("document_detail", slug)`.
- `linkify_internal_refs(text, links)` принимает теперь dict `links`
  (`anchors`/`numbers`/`codices`); обратная совместимость: если передан set — это anchors.
  Порядок в одном проходе по экранированному абзацу: внутренние «ст. N» (#49) → внешние
  «N-ФЗ» (`_FZ_RE` локально, без импорта ingestion) → кодексы (regex'ы из `links`). Вставки
  не пересекаются (числа/кодексы/якоря — разные токены; URL-слаги без «-ФЗ»/«кодекс»).
  XSS-safe (экранируем ДО линковки).

### Интеграция
- `documents/templatetags/doc_refs.py:linkify_refs` — без изменений сигнатуры (передаём dict).
- `_article_node.html`: `linkify_refs:anchors` → `linkify_refs:links`.
- `document_detail` + `document_print` views: вместо `anchors=...` кладут
  `links = {"anchors": …, **build_corpus_links(exclude_slug=document.slug)}`.

## Тесты
`documents/tests/test_cross_links.py` (django_db — нужен корпус): два акта (tk-rf 197-ФЗ +
sout-426-fz 426-ФЗ); текст одной статьи упоминает «426-ФЗ» и «Трудовым кодексом» → reader
страница содержит `href="/doc/sout-426-fz/"` и `href="/doc/tk-rf/"`. Плюс чистые unit-тесты
`linkify_internal_refs` с dict-резолвером (число/кодекс резолвятся, нерезолвленные — текст,
экранирование сохраняется). Не трогаем hotspot test_views.py.

## Риск
Аддитивно: refs.py/templatetag/шаблон/контекст view (все на main, не заняты открытыми PR
#53-55). Ноль моделей/миграций. XSS-safe. Обратимо. Перф: `build_corpus_links` — 1-2 запроса
на страницу (малый корпус).
