# Хвост консистентности UI — дизайн (2026-06-22)

Doc serves as both spec and plan — правка мелкая (4 шаблонных однострочника + 1 тест-файл).

## Проблема

Два класса UI-консистентности, для которых правки УЖЕ одобрены ранее (PR #39 — guard
пустого `official_number`; PR #40 — единый формат дат `ДД.ММ.ГГГГ`), имеют пропущенные
инстансы. Это последний хвост обоих классов.

**Класс A — сырая `redaction_date` (ISO) утекает пользователю** вместо `|date:"d.m.Y"`.
Везде в читательских шаблонах дата уже форматируется (`document_detail.html`,
`changes_feed.html`), но три места пропущены:
- `templates/documents/redaction_diff.html:9` — **читатель** (заголовок diff-страницы).
- `templates/admin/documents/redaction/diff.html:12` — **куратор** (админский diff).
- `templates/admin/documents/redaction/review_queue.html:11` — **куратор** (очередь ревью).

**Класс B — висячий «№ » при пустом `official_number`** (`blank=True`). Эталонный guard
уже есть в `templates/documents/_list_items.html:5`
(`{% if doc.official_number %} № {{ doc.official_number }}{% endif %}`), а
`document_detail.html:10` использует `|default:"—"`. Пропущено:
- `templates/search/_results.html:10` — **читатель**: при пустом номере рендерит
  «Тип №  · Действует» (висячий «№», двойной пробел перед « · »).

## Решение

Шаблонные однострочники, повторяющие уже принятые в кодовой базе паттерны.

| Файл | Правка |
|---|---|
| `templates/documents/redaction_diff.html:9` | обе `redaction_date` → `… |date:"d.m.Y"` |
| `templates/search/_results.html:10` | обернуть `№ {{ official_number }}` в `{% if r.document.official_number %}` |
| `templates/admin/documents/redaction/diff.html:12` | `redaction_date` → `… |date:"d.m.Y"` |
| `templates/admin/documents/redaction/review_queue.html:11` | `redaction_date` → `… |date:"d.m.Y"` |

### Почему шаблонный фильтр, а не глобальный `USE_L10N`/`DATE_FORMAT`

Та же логика, что в PR #40: явный `|date:"d.m.Y"` хирургичен и совпадает с 5+
существующими call-site'ами. Глобальный флаг молча переформатировал бы виджеты дат в
Django admin и round-trip форм — реальная регрессия ради нулевой выгоды. Отклонено.

### Guard `№`

Точно копируем паттерн `_list_items.html:5`: показывать « № <номер>» только если
`official_number` непуст. У актов без номера блок исчезает целиком, « · <статус>»
остаётся валидным.

## Тестирование

Новый изолированный файл `documents/tests/test_consistency_tail.py` (hotspot
`documents/tests/test_views.py` НЕ трогаем — установившаяся практика). TDD RED→GREEN:

1. **redaction_diff дата (читатель):** опубликовать 2 редакции акта, GET
   `/doc/<slug>/diff/<from_pk>/` под авторизованным пользователем → ассертить, что в HTML
   есть отформатированная `ДД.ММ.ГГГГ` строка и НЕТ сырого ISO `ГГГГ-ММ-ДД`.
2. **search results guard (читатель):** документ с пустым `official_number`, проиндексировать,
   GET `/search/?q=…` → ассертить отсутствие висячего «№ » (нет подстроки «№  ·» / «№ </small>»)
   и присутствие статуса.
3. **(опц., если дёшево) admin diff/review_queue дата (куратор):** под staff-клиентом
   проверить отформатированную дату — иначе покрыть редакторские шаблоны не тестом, а
   ревью (они тривиальны, тот же фильтр).

## Риск

Околонулевой — только отображение. Ноль моделей/миграций/зависимостей. Обратимо.

## Вне scope

Хлебные крошки на `document_detail`, доступность формы поиска, счётчик корпуса,
типографика заголовков статей — это НОВАЯ scope (см. кандидатов сессии), не этот хвост.
