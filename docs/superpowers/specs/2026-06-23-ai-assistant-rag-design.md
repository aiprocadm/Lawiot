# AI-ассистент по трудовому праву (RAG) — дизайн (2026-06-23)

Трек «AI» из брейншторма 2026-06-14/06-17 («лучший по трудовому праву = ниша + глубина +
AI»). Цель — отличие от Гарант/Консультант/Контур: задать вопрос на естественном языке →
получить ответ, **обоснованный ТОЛЬКО корпусом**, с ссылками на конкретные статьи.

Реализуется срезами (slices). **Этот документ = срез 1**: слой извлечения (RAG-retrieval) +
синтез обоснованного ответа через Claude API + изящная деградация без API-ключа.

## Принципы (юридический продукт — цена ошибки высока)

1. **Никаких галлюцинаций права.** Модель отвечает ИСКЛЮЧИТЕЛЬНО по переданным статьям
   корпуса. Если ответа в них нет — прямо сказать «в корпусе не нашлось», НЕ выдумывать.
2. **Всегда цитировать.** Каждое утверждение привязано к статье (deep-link `st-N`).
3. **Не юридическая консультация.** Дисклеймер: справочная информация, не консультация.
4. **Дёшево и low-maintenance по умолчанию.** Без `ANTHROPIC_API_KEY` фича работает в
   режиме «только извлечение» (показывает релевантные статьи, без синтеза) — ноль затрат,
   ноль риска галлюцинаций. Синтез включается, только когда ключ настроен.
5. **За `@login_required`** (§10 — весь просмотрщик за логином).

## Архитектура — новое приложение `assistant`

Изоляция: отдельное Django-приложение, чистые границы, переиспользует `search`/`documents`.

### `assistant/retrieval.py` — слой извлечения (чистый, без сети)
- `RetrievedArticle` dataclass: `document_title`, `article_label` (e.g. «Статья 81»),
  `anchor`, `url` (`/doc/<slug>/#<anchor>`), `text` (полный текст статьи), `rank`.
- `retrieve(question, *, limit=8) -> list[RetrievedArticle]`:
  1. `search_documents(question)` (переиспользуем FTS+лемматизацию+синонимы #20/#28);
  2. берём топ-`limit` результатов **со статьёй** (article_anchor не None — нам нужна
     цитируемая единица; redaction-хиты без статьи пропускаем для контекста);
  3. для каждого победителя достаём `Article.text` одним запросом (`anchor`-ы уникальны в
     рамках редакции; джойн по published current-редакции);
  4. строим `url`, `article_label` из `SearchResult`.
- Тестируемо на реальном FTS, без ключа.

### `assistant/prompts.py` — системный промпт (юр-guardrails)
- `SYSTEM_PROMPT` (рус.): «Ты — справочный ассистент по трудовому праву РФ. Отвечай
  СТРОГО на основе приведённых статей. Если ответа в них нет — скажи об этом, не выдумывай.
  Каждое утверждение сопровождай ссылкой на статью (Статья N). Это справочная информация,
  не юридическая консультация. Отвечай по-русски, кратко и по делу.»
- `build_user_content(question, articles)` — собирает блок контекста: вопрос + пронумерованные
  статьи (заголовок-цитата + текст). Чистая функция.

### `assistant/services.py` — оркестрация
- `AssistantAnswer` dataclass: `question`, `articles` (list[RetrievedArticle]),
  `answer_text` (str|None — None в retrieval-only), `mode` («synthesized»|«retrieval_only»|
  «no_results»), `error` (str|None).
- `answer_question(question, *, client=None) -> AssistantAnswer`:
  1. `retrieve(...)`; если пусто → `mode="no_results"`.
  2. Если ключа/SDK нет (или передан `client=None` и нечем строить) → `mode="retrieval_only"`
     (вернуть статьи, `answer_text=None`).
  3. Иначе вызвать Claude (`claude-opus-4-8`, `thinking={"type":"adaptive"}`,
     `max_tokens≈4000`, non-streaming — ответы короткие): system=`SYSTEM_PROMPT`,
     user=`build_user_content(...)`. Извлечь текст. На `stop_reason=="refusal"` или ошибку
     API → `error`, откат в retrieval-only (статьи всё равно полезны).
- **Внедрение клиента**: `client` параметризуем (по умолчанию ленивая фабрика
  `_default_client()` через env-ключ). Тесты передают фейковый клиент → ноль сети, ключ не
  нужен в CI. Импорт `anthropic` защищён `try/except ImportError` (фича работает и без пакета
  — режим retrieval-only).
- Ключ: `settings.ANTHROPIC_API_KEY` (django-environ, default `""`). Пусто → retrieval-only.

### `assistant/views.py` — страница `/assistant/`
- `@login_required assistant_view`: GET с `?q=` → форма + результат `answer_question`.
  HTMX-частичка `_answer.html` для живого ответа (как поиск), полная `assistant.html` иначе.
- Рендерит: ответ (если есть), дисклеймер, список цитированных статей с deep-link'ами,
  пустые состояния («Задайте вопрос», «В корпусе не нашлось…», баннер retrieval-only).

### Прочее
- `config/urls.py`: `path("assistant/", include("assistant.urls"))` за `@login_required`.
- nav-ссылка «Ассистент» в `base.html`.
- `config/settings.py`: `ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")`;
  `INSTALLED_APPS += ["assistant"]`.
- `requirements.txt`: `anthropic>=0.40` (чистый wheel; импорт защищён — отсутствие пакета
  не ломает фичу).

## Модель и параметры Claude API (из skill `claude-api`)

- Модель `claude-opus-4-8` (дефолт, самый способный Opus-tier).
- `thinking={"type": "adaptive"}` (адаптивное мышление — рекомендованное).
- `max_tokens≈4000`, non-streaming (ответы короткие, <16k — таймаут не грозит).
- SDK `anthropic`, клиент `anthropic.Anthropic()` (ключ из env `ANTHROPIC_API_KEY`).
- Обработка `stop_reason=="refusal"` перед чтением `content`.
- Типизированные исключения (`anthropic.APIError` и подклассы) → graceful откат.

## Тестирование (TDD)

Изолированные тесты в `assistant/tests/` (не трогаем чужие hotspot-файлы):
- `test_retrieval.py` (django_db, реальный FTS): вопрос → статьи с url/anchor/label/text;
  пустой запрос → []; только статейные хиты; лимит.
- `test_services.py`: (a) нет ключа → `retrieval_only`; (b) фейковый клиент возвращает текст
  → `synthesized` + answer_text; (c) фейк бросает `APIError`/возвращает `refusal` → откат в
  retrieval_only с `error`; (d) нет результатов → `no_results`. Ноль сети (инъекция клиента).
- `test_views.py` (assistant): login-gate; GET без q → форма; GET с q → ответ/статьи;
  HTMX → частичка.
- `test_prompts.py`: `build_user_content` включает вопрос+тексты статей; SYSTEM_PROMPT
  содержит guardrail-фразы.

Прогон через WSL Postgres-фолбэк (Docker мёртв); `anthropic` доустановить в WSL-venv (нужен
для импорта в services при наличии; но тесты сервиса инъектируют фейк — реальный пакет не
требуется, импорт защищён).

## Риск и обратимость

- Аддитивно: новое приложение, ноль изменений существующих моделей/миграций (нет новых
  таблиц в срезе 1 — ответы не персистятся). Полностью обратимо.
- Стоимость: ноль по умолчанию (нет ключа → retrieval-only). С ключом — оплата за запросы;
  это сознательный выбор оператора (env-флаг).
- Безопасность данных: запросы пользователя уходят в Claude API только при настроенном ключе;
  ничего не логируется сверх обычного.

## Вне scope (следующие срезы)
- Стриминг ответа в UI; многоходовой диалог/история; семантический поиск (pgvector +
  эмбеддинги); кэш ответов; объяснение diff редакций; перенос в Managed Agents. Срез 1 —
  фундамент (retrieve → grounded synthesize → cite), на нём строится остальное.
