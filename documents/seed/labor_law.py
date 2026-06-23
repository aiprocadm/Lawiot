"""Стартовый корпус трудового права. source_url заполняются рабочими ссылками
из официального источника (этап захвата фикстур). auto_ingest=True включается
для акта только после успешной приёмки парсера на нём."""

import datetime

SEED_ACTS = [
    {
        "slug": "tk-rf",
        "doc_type": "code",
        "title": "Трудовой кодекс Российской Федерации",
        "official_number": "197-ФЗ",
        "issuing_body": "Федеральное Собрание Российской Федерации",
        "status": "in_force",
        "level": "federal",
        "source_status": "official",
        "sign_date": datetime.date(2001, 12, 30),  # подписан Президентом 30.12.2001
        "official_pub_date": datetime.date(2001, 12, 31),  # «Российская газета» №256
        # ИПС «Законодательство России» (pravo.gov.ru). Эндпоинт doc_itself отдаёт
        # консолидированный текст (базовый ?docbody= — лишь селектор редакций).
        # ВАЖНО: print=1 обязателен (без него ответ обрезается ~620КБ — ТК РФ
        # обрывался на ст. 181), а rdk НЕ указываем: без него ИПС отдаёт
        # АКТУАЛЬНУЮ редакцию (rdk=0 — это исходный текст 2001 года!).
        # Кодировка windows-1251; детали в
        # docs/superpowers/notes/2026-06-08-real-fixtures-characterization.md
        "source_url": "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=102074279&print=1",
        "auto_ingest": True,  # приёмка пройдена (2026-06-10): акт опубликован, парсер ОК
        # §17 авто-консолидация: ежедневный обход сам публикует свежую сводную
        # редакцию. Включено после сквозной приёмки на живой фикстуре (дата редакции
        # = последняя поправка, гейт AUTOPUBLISH_MIN_RATIO защищает от обрезка):
        # см. test_real_tk_rf_auto_publishes_consolidated_redaction.
        "auto_publish": True,
    },
    {
        "slug": "sout-426-fz",
        "doc_type": "federal_law",
        "title": "О специальной оценке условий труда",
        "official_number": "426-ФЗ",
        "issuing_body": "Федеральное Собрание Российской Федерации",
        "status": "in_force",
        "level": "federal",
        "source_status": "official",
        "sign_date": datetime.date(2013, 12, 28),  # подписан 28.12.2013
        "official_pub_date": datetime.date(2013, 12, 30),  # «Российская газета» №295
        "source_url": "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=102170672&print=1",
        # Приёмка парсера пройдена на живой фикстуре (4 главы, ≥27 статей, без «сирот»):
        # см. test_real_sout426_ingest_creates_clean_draft. auto_ingest даёт лишь
        # ЧЕРНОВИКИ для куратора (auto_publish остаётся False — без авто-публикации).
        "auto_ingest": True,
    },
    {
        "slug": "prof-10-fz",
        "doc_type": "federal_law",
        "title": "О профессиональных союзах, их правах и гарантиях деятельности",
        "official_number": "10-ФЗ",
        "issuing_body": "Федеральное Собрание Российской Федерации",
        "status": "in_force",
        "level": "federal",
        "source_status": "official",
        "source_url": "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=102039060&print=1",
        # Приёмка парсера пройдена на живой фикстуре (6 глав РИМСКИМИ цифрами, ≥33
        # статьи, без «сирот»): см. test_real_prof10_ingest_creates_clean_draft.
        # Потребовала расширения CHAPTER_RE на римские номера глав. auto_ingest даёт
        # лишь ЧЕРНОВИКИ для куратора (auto_publish остаётся False).
        "auto_ingest": True,
    },
    {
        "slug": "mrot-82-fz",
        "doc_type": "federal_law",
        "title": "О минимальном размере оплаты труда",
        "official_number": "82-ФЗ",
        "issuing_body": "Федеральное Собрание Российской Федерации",
        "status": "in_force",
        "level": "federal",
        "source_status": "official",
        "source_url": "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=102066375&print=1",
        # Приёмка парсера пройдена на живой фикстуре. ПЛОСКИЙ акт: глав нет, только
        # статьи 1–9 верхнего уровня (см. test_real_mrot82_ingest_creates_clean_draft).
        # auto_ingest даёт лишь ЧЕРНОВИКИ для куратора (auto_publish остаётся False).
        "auto_ingest": True,
    },
]

# Ожидаемые акты: хотим в корпусе, но пока нет доступного источника. Видны куратору
# в admin (модель PendingAct) как напоминание; заводятся вручную, когда появятся.
# (Заменяет прежний комментарий-список кандидатов: 10-ФЗ и 82-ФЗ уже в SEED_ACTS.)
PENDING_ACTS = [
    {
        "slug": "zanyatost-565-fz",
        "doc_type": "federal_law",
        "title": "О занятости населения в Российской Федерации",
        "official_number": "565-ФЗ",
        "note": (
            "Активный закон 2023 г. не отдаётся классической ИПС через doc_itself "
            "(там только отменённый предшественник — Закон РФ 1032-1, «Утратил силу»); "
            "на publication.pravo.gov.ru — скан-PDF исходной редакции (нужен OCR, и это "
            "не консолидированный текст). Ждём появления консолидированного 565-ФЗ в ИПС."
        ),
        "ips_search_url": "http://pravo.gov.ru/proxy/ips/?start_search&fattrib=1",
    },
]
