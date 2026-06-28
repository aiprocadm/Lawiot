# Починка якорей дефисных статей + UNIQUE(redaction, anchor)

Дата: 2026-06-29
Ветка: `fix/deferred-audit-items`
Статус: согласовано, готово к плану реализации

## 1. Проблема

Парсер статей до коммита c99c9a7 терял дефисный суффикс номера. `ARTICLE_RE`
захватывал только `\d+(?:\.\d+)?`, поэтому заголовок «Статья 123.20-1. Личный
фонд» разбирался как `number="123.20"`, `title="-1. Личный фонд"`. Реальные
дефисные статьи схлопывались на базовый номер:

- ГК РФ: 123.20-1 … 123.20-8 (личный фонд) → все на «123.20»;
- ТК РФ: 341.1-1 … (заёмный труд) → все на «341.1».

Следствие: совпадающие `anchor` (`st-123-20`) внутри одной редакции → дубли
групп `(redaction, anchor)` → 500 (`MultipleObjectsReturned`) на странице
разъяснения, неверные `number` и `title` (суффикс «-N» утёк в заголовок).

Корень исправлен в c99c9a7 (`ARTICLE_RE` теперь ловит `(?:-\d+)?`), поэтому
**новые** импорты корректны. Но уже засеянный корпус (6691 строка `Article`,
~33 дубль-группы) был импортирован до правки и остаётся «грязным».

Цель из двух частей:
1. Починить существующий корпус: каждая статья получает корректный дефисный
   `number`/`anchor`/`title`.
2. После того как дублей `(redaction, anchor)` не осталось — добавить частичное
   `UNIQUE(redaction, anchor) WHERE anchor != ''` на `documents.Article`, чтобы
   регрессия была невозможна.

## 2. Ключевые факты (из исследования кода)

- `Redaction.full_text` хранит нормализованный исходный текст, из которого
  парсились статьи (`ingestion/services.py::create_draft_from_parsed`:
  `redaction.full_text = parsed.full_text`). Проверено: корректные заголовки
  «Статья 123.20-1.» в `full_text` присутствуют. Значит, переразбор из
  `full_text` исправленным парсером возможен **без сети**.
- Правка парсера c99c9a7 — только дефисный суффикс в `ARTICLE_RE`. Регэксп
  по-прежнему якорится на `^Статья\s+\d+`, поэтому матчит **те же** строки-
  заголовки. Переразбор **инвариантен по числу узлов**: тот же `order`, тот же
  `kind`, та же структура `parent`. Меняются только `number`/`title` (и,
  следовательно, `anchor`) у дефисных статей.
- `Article.embedding` (pgvector) считается **только из `article.text`**
  (`documents/management/commands/embed_articles.py::_embed_batch`:
  `embed_passages([a.text for a in articles])`). При переразборе суффикс уходит
  из `title` обратно в `number`, а тело `text` **байт-в-байт идентично** →
  эмбеддинги **не требуют** перегенерации.
- Якорь/FK на `Article` нигде не хранится, кроме `Link.from_article` /
  `Link.to_article` (оба `SET_NULL`) и `Article.parent` (self-CASCADE).
  `Bookmark`/`ViewHistory` ключуются на `document`; `Note.article_number` —
  свободный текст. Обновление строк **на месте** (без delete/recreate)
  сохраняет все FK `Link` и указатели `parent`.
- `search_vector` статьи индексирует `number`+`title`+`text`
  (`Redaction.update_search_index`), поэтому это **единственное** производное
  поле, которое надо обновить — чистым SQL `SearchVector`, без модели и сети.
- Сидер `seed_corpus` заводит только метаданные `Document` (без редакций и
  статей). Строки `Article` создаёт конвейер приёма. Значит, на свежей/тестовой
  БД статей нет → миграция-ограничение безопасна на пустой БД, а починка — это
  разовая операция на заполненных БД. Фикстуры с «зашитым» багом нет.

## 3. Механизм починки

Хирургическая перенумерация на месте (не пересоздание). Для каждой редакции:

1. `reparsed = parse_text(redaction.full_text, redaction.document.doc_type).articles`.
2. `existing = list(Article.objects.filter(redaction=r).order_by("order", "pk"))`.
3. **Защита выравнивания**: если `len(existing) != len(reparsed)` или хоть один
   `kind` попарно не совпал — редакция **пропускается** и пишется в отчёт
   (`skipped`). Данные не трогаются. (Страховка от редакций, засеянных другим
   парсером.)
4. Для каждой пары `(row, node)`: если `row.number != node.number` или
   `row.title != node.title` — выставить `row.number`, `row.title`,
   `row.anchor = compute_anchor(node.kind, node.number)`; собрать в список на
   `bulk_update(["number", "title", "anchor"])` и запомнить PK.
5. Обновить `search_vector` по изменённым PK (`SearchVector` напрямую).
6. **Пост-проверка**: внутри редакции не осталось дублей `anchor` (иначе
   `raise` → откат транзакции редакции).

Не трогаем: `embedding`, `Link.*_article`, `parent`, `order`. Идемпотентно:
повторный запуск ничего не меняет.

## 4. Компоненты

### 4.1 `documents/repair.py` (общая чистая функция)

```
repair_redaction_anchors(redaction, *, Article, parse_text, compute_anchor) -> RepairReport
```

- Работает и с конкретными, и с историческими моделями: использует только
  queryset / `.update()` / `SearchVector` — никаких методов модели.
- `parse_text` и `compute_anchor` передаются параметрами (команда и миграция
  передают `ingestion.parsing.parse_text` и `documents.models.compute_anchor`),
  чтобы функция сама не хардкодила импорт прикладной логики.
- `RepairReport` (датакласс): `changed_articles: int`, `changed: bool`,
  `skipped: bool`, `skip_reason: str | None`.
- Каждая редакция чинится в собственной `transaction.atomic()`.

### 4.2 `documents/models.py` (устранение дублирования)

Вынести логику якоря из `Article.save()` в модуль:

```python
_ANCHOR_PREFIX = {"section": "razdel", "chapter": "glava",
                  "article": "st", "point": "p", "appendix": "pril"}

def compute_anchor(kind: str, number: str) -> str:
    prefix = _ANCHOR_PREFIX[kind]          # неизвестный kind → KeyError (как раньше)
    return f"{prefix}-{slugify(number.replace('.', '-'))}"
```

`Article.save()` зовёт `compute_anchor(self.kind, self.number)`. Поведение и
сигнатура якоря не меняются (KeyError на неизвестный `kind` сохраняется).

### 4.3 `documents/management/commands/repair_article_anchors.py`

- `--dry-run` — только отчёт, без записи (откатывает транзакции).
- По умолчанию применяет. Транзакция на каждую редакцию.
- Печатает: число изменённых статей, число изменённых/пропущенных редакций,
  итоговое число дубль-групп `(redaction, anchor)` после прохода.
- Оборачивает `repair_redaction_anchors`, передавая конкретные модели,
  `parse_text`, `compute_anchor`.

### 4.4 `documents/migrations/00XX_repair_and_uniq_anchor.py`

- `RunPython(repair_all, noop)`:
  - лениво импортирует `parse_text`/`compute_anchor` внутри функции;
  - `Redaction = apps.get_model("documents", "Redaction")`,
    `Article = apps.get_model("documents", "Article")`;
  - проходит по всем редакциям через общую функцию;
  - no-op на пустой БД (CI/тесты), самоисцеление на заполненной;
  - обратная операция — `noop` (откат починки не делаем).
- `AddConstraint(UniqueConstraint(fields=["redaction", "anchor"],
  condition=~Q(anchor=""), name="uniq_article_redaction_anchor"))`,
  продублировано в `Article.Meta.constraints`. Обратная — снятие.
- Порядок операций в одном файле гарантирует: сначала чистим, потом ставим
  ограничение.

## 5. Охват и осознанно не трогаем

- Починка идёт по **всем** редакциям (включая черновики): ограничение per-
  redaction, и `AddConstraint` упал бы на «грязном» черновике.
- `Note.article_number` (свободный текст) не переписываем — намерение
  пользователя неизвестно, а базовая статья «123.20» по-прежнему существует.
- Оборонительный обход «первая по order» в `documents/views.py::article_explain`
  оставляем (после починки дублей быть не может; обход безвреден). Вне охвата.

## 6. Тесты

`documents/tests/test_repair.py` (+ тесты ограничения и команды):

- **Починка**: редакция с `full_text`, содержащим «Статья 123.20-1.» и т.п., и
  строками `Article`, имитирующими старый разбор (`number="123.20"`,
  `title="-1. …"`, дублирующийся `anchor="st-123-20"`). После починки: номера/
  якоря корректны, дублей 0; **embedding сохранён** (ставим вектор, проверяем
  неизменность); **`Link.from_article` сохранён** (тот же PK); `search_vector`
  обновлён.
- **Защита выравнивания**: переразбор даёт другое число узлов → редакция
  пропущена, строки не тронуты.
- **Идемпотентность**: второй запуск — no-op (`changed == False`).
- **Извлечение `compute_anchor`**: `Article.save()` по-прежнему выводит якорь.
- **Ограничение**: дубль `(redaction, anchor)` → `IntegrityError`; две строки с
  `anchor=''` в одной редакции разрешены.
- **Команда**: `--dry-run` ничего не пишет; реальный запуск чистит корпус.

## 7. Проверка (критерии готовности)

- Запрос дублей `Article.objects.exclude(anchor='').values('redaction','anchor')
  .annotate(n=Count('id')).filter(n__gt=1)` → пусто.
- `.venv\Scripts\python.exe -m pytest` — ≥494 зелёных (нужен контейнер
  lawiot-db на :5433).
- `ruff check` — чисто.
- `python manage.py makemigrations --check` — без незакоммиченных миграций.

## 8. Порядок работ

1. Извлечь `compute_anchor` в `documents/models.py`, переключить `save()`.
2. Написать `documents/repair.py` (+ `RepairReport`).
3. Тесты на чистую функцию и извлечение якоря (TDD).
4. Management-команда `repair_article_anchors` (+ дымовой тест).
5. Прогнать команду на dev-корпусе (`--dry-run`, затем применить); проверить
   запрос дублей → 0.
6. Добавить ограничение в `Article.Meta` + миграция (RunPython + AddConstraint);
   тесты ограничения.
7. Полная проверка: pytest, ruff, makemigrations --check.
