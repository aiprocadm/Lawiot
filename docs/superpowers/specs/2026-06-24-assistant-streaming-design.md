# Дизайн: стриминг ответа ассистента (AI-срез 2)

Дата: 2026-06-24. Roadmap §3-C, срез 2: «стриминг ответа в UI (SSE/htmx) —
мгновенная отзывчивость».

## Проблема

`assistant_view` синхронно блокирует HTTP-запрос на ~10–30 с, пока Opus
генерирует grounded-ответ (до 16k токенов, включая adaptive-мышление). Пользователь
видит спиннер и пустоту до самого конца. Классические СПС только подступаются к
AI — стриминг усиливает наш дифференциатор отзывчивостью.

## Не-цели (YAGNI)

- НЕ перевод на ASGI/async Django — остаёмся на sync WSGI + gunicorn.
- НЕ стриминг для article-explain / diff-explain в reader (отдельные одноразовые
  фичи; этот срез — про диалоговый ассистент).
- НЕ новые JS-зависимости (htmx-sse, websockets). Чистый `fetch` + `ReadableStream`.
- НЕ серверный push-канал (SSE long-lived). Одноразовый стрим на ответ.

## Архитектура

Три части: сервисный генератор, стриминг-вью, прогрессивный фронтенд. Существующий
блокирующий `assistant_view` СОХРАНЯЕТСЯ как fallback без JS.

### 1. `assistant/services.py` — `stream_answer()`

Новая функция рядом с `answer_question` (общий retrieval/клиент/прокси-логика):

```
def stream_answer(question, *, document=None, history=None, client=None):
    """Вернуть (articles, deltas) — список статей-оснований (готов сразу,
    для немедленной отрисовки) и генератор текстовых дельт ответа (str).

    deltas пуст, если: нет статей (no_results), нет клиента (retrieval_only),
    либо API-ошибка по ходу стрима (грациозная деградация — что успело
    стримнуться, остаётся; финал считается по накопленному тексту)."""
```

- `retrieve()` — синхронно, до стрима (быстрые DB-запросы; статьи нужны для
  немедленной отрисовки и для проверки цитат в финале).
- Синтез через `client.messages.stream(...)` (те же `MODEL`/`MAX_TOKENS`/
  `thinking`/`output_config`/`SYSTEM_PROMPT`/`messages`, что у `answer_question`);
  генератор отдаёт `stream.text_stream` (только текст, не мышление).
- Любое исключение внутри стрима → лог + аккуратное завершение генератора
  (без падения вью).

Хелпер `finalize_answer(question, articles, text)` → `AssistantAnswer` (mode по
наличию текста; `unverified_citations(text, articles)`), чтобы вью собрал ход для
сессии без дублирования логики.

`answer_question` НЕ трогаем — общий код выносим в маленькие приватные хелперы
(`_synthesis_messages`, `_default_client` уже есть), сохраняя поведение и тесты.

### 2. `assistant/views.py` — `assistant_stream` (новый вью)

`GET /assistant/stream/?q=...&doc=...` → `StreamingHttpResponse`
(`content_type="text/plain; charset=utf-8"`, заголовок `X-Accel-Buffering: no`
чтобы прокси не буферизовал):

1. Прочитать `q`, `document`, `history` из сессии (как в `assistant_view`).
2. `articles, deltas = stream_answer(...)`.
3. Тело-генератор: `for chunk in deltas: acc.append(chunk); yield chunk`.
4. **Финализатор генератора** (после стрима): собрать ход
   (`finalize_answer` + словарь как в `assistant_view`), дописать в
   `conversation[-MAX_TURNS:]`, `request.session[SESSION_KEY] = ...`, и
   **`request.session.save()` ЯВНО** — потому что `SessionMiddleware.process_response`
   уже отработал к моменту стрима тела; cookie `sessionid` у залогиненного
   пользователя уже есть, нужен лишь серверный апдейт стора.

`@login_required`. Без `q` — пустой стрим (ничего не персистим).

### 3. Фронтенд (`templates/assistant/assistant.html` + маленький инлайн-скрипт)

- Форму с `hx-get` заменить на обычную (`id="assistant-form"`, `action` на
  `assistant_view` — fallback без JS: обычный GET → полная страница с блокирующим
  ответом, как сейчас).
- Инлайн-скрипт перехватывает `submit`:
  1. `preventDefault`; добавить в `#assistant-conv` скелет хода: эхо вопроса +
     пустой `<div class="stream-answer" aria-live="polite">`.
  2. `fetch('/assistant/stream/?q=...&doc=...')`, читать `response.body` ридером,
     декодировать чанки, дописывать `textContent` в `.stream-answer`.
  3. По завершении стрима — перезагрузить ленту: `fetch(assistantUrl, {headers:{'HX-Request':'true'}})`
     → заменить `#assistant-conv` свежим partial (статьи-основания, бейдж
     непроверенных цитат, форматирование — из персистнутой сессии). Текст тот же →
     минимальный фликер.
  4. Очистить поле ввода.
- Скрипт ~30 строк ванильного JS, без зависимостей. `linebreaksbr`/details/бейджи
  остаются в `_conversation.html` (не дублируются в JS).

Режимы no_results / retrieval_only: стрим пуст, финал-reload показывает корректное
сообщение/статьи из сессии. Стриминг — чистое прогрессивное улучшение
синтез-режима.

## Инфраструктура

`docker-compose.yml`: gunicorn получает `--workers 3 --timeout 120`. При 1 sync-
воркере один активный стрим заблокировал бы всё приложение; 3 воркера хватает для
внутреннего инструмента (низкая конкуренция). Без повторяющейся стоимости —
только память. `--timeout 120` — стрим может длиться >30 c дефолта.

## Обработка ошибок

- Нет ключа/пакета `anthropic` → `deltas` пуст → retrieval_only (как сейчас).
- API-ошибка/refusal в начале → пустой стрим → reload покажет retrieval_only.
- API-ошибка В СЕРЕДИНЕ стрима → что стримнулось остаётся; финал по накопленному
  тексту (если непусто — synthesized, иначе retrieval_only). Лог warning.
- JS отключён/упал → форма делает обычный GET → блокирующий полностраничный ответ
  (текущее поведение). Деградация без потери функциональности.

## Тестирование

- `stream_answer`: фейк-клиент с `.messages.stream()` → контекст-менеджер с
  `text_stream`, отдающим дельты; проверить накопление, retrieval_only без клиента,
  no_results без статей, грациозную деградацию на исключении.
- `assistant_stream` вью (Django test client): `response.streaming_content` →
  склеить дельты; проверить что после стрима ход персистнут в сессии
  (`client.session[SESSION_KEY]`), что `@login_required` редиректит аноним,
  что history из сессии передаётся.
- `finalize_answer`: mode/unverified по тексту.
- Существующие тесты `answer_question`/`assistant_view` остаются зелёными
  (поведение не меняется).

## План отката

Фича аддитивна: новый вью + URL + сервисная функция + JS + флаг воркеров.
Откат — revert PR; блокирующий путь продолжает работать.
