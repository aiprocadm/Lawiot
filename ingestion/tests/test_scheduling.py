from io import StringIO

import httpx
import pytest
from django.core.management import call_command

from documents.models import Redaction
from documents.tests.factories import make_document
from ingestion.scheduling import iter_targets, run_sweep, sweep_targets

# HTML с маркером «Статья 1.» в UTF-8 — парсер 3a извлечёт одну статью → черновик.
HTML = "<p>Статья 1. Общие положения</p><p>текст</p>".encode("utf-8")


def _router(handler_by_path):
    def handler(request):
        return handler_by_path[request.url.path](request)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_iter_targets_selects_only_flagged_docs_with_source_url():
    make_document(slug="a", official_number="1", auto_ingest=True, source_url="https://e.test/a")
    make_document(  # flagged but no URL → excluded
        slug="b", official_number="2", auto_ingest=True, source_url=""
    )
    make_document(  # has URL but not flagged → excluded
        slug="c", official_number="3", auto_ingest=False, source_url="https://e.test/c"
    )
    targets = list(iter_targets())
    assert len(targets) == 1
    t = targets[0]
    assert t.document.slug == "a"
    assert t.url == "https://e.test/a"
    assert t.target_key == "a"  # конвенция target_key = slug (как у ingest_url)


@pytest.mark.django_db
def test_sweep_creates_drafts_isolates_failures_and_counts():
    make_document(slug="ok", official_number="1", auto_ingest=True, source_url="https://e.test/ok")
    make_document(
        slug="bad", official_number="2", auto_ingest=True, source_url="https://e.test/bad"
    )
    client = _router(
        {
            "/ok": lambda r: httpx.Response(
                200, headers={"content-type": "text/html"}, content=HTML
            ),
            "/bad": lambda r: httpx.Response(500, content=b"boom"),
        }
    )
    summary = sweep_targets(client=client)
    assert summary.total == 2
    assert summary.success == 1
    assert summary.failed == 1
    assert summary.skipped == 0
    assert Redaction.objects.filter(document__slug="ok").count() == 1  # черновик создан
    assert Redaction.objects.filter(document__slug="bad").count() == 0  # сбой изолирован


@pytest.mark.django_db
def test_sweep_skips_unchanged_on_second_run():
    make_document(slug="ok", official_number="1", auto_ingest=True, source_url="https://e.test/ok")
    ok = {"/ok": lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=HTML)}
    first = sweep_targets(client=_router(ok))
    second = sweep_targets(client=_router(ok))
    assert first.success == 1
    assert second.success == 0
    assert second.skipped == 1


@pytest.mark.django_db
def test_sweep_continues_when_ingest_target_raises(monkeypatch):
    make_document(slug="a", official_number="1", auto_ingest=True, source_url="https://e.test/a")
    make_document(slug="b", official_number="2", auto_ingest=True, source_url="https://e.test/b")
    from ingestion import scheduling

    seen = []

    def boom(target, client=None):
        seen.append(target.target_key)
        raise RuntimeError("сбой уровня БД")

    monkeypatch.setattr(scheduling, "ingest_target", boom)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x"))
    )
    summary = sweep_targets(client=client)
    assert summary.total == 2
    assert summary.failed == 2
    assert len(seen) == 2  # обход не прервался на первом исключении


@pytest.mark.django_db
def test_run_sweep_returns_summary_string():
    result = run_sweep()
    assert isinstance(result, str)
    assert "всего=" in result


@pytest.mark.django_db
def test_sweep_targets_command_reports_summary():
    out = StringIO()
    call_command("sweep_targets", stdout=out)  # без целей → нулевая сводка, без сети
    assert "Обход завершён" in out.getvalue()
    assert "всего=0" in out.getvalue()


@pytest.mark.django_db
def test_ensure_sweep_schedule_is_idempotent():
    from django_q.models import Schedule

    call_command("ensure_sweep_schedule")
    call_command("ensure_sweep_schedule")  # повтор не создаёт дубль
    qs = Schedule.objects.filter(name="daily-sweep")
    assert qs.count() == 1
    sched = qs.get()
    assert sched.func == "ingestion.scheduling.run_sweep"
    assert sched.schedule_type == Schedule.CRON


@pytest.mark.django_db
def test_ensure_sweep_schedule_updates_cron(settings):
    from django_q.models import Schedule

    settings.SWEEP_CRON = "0 5 * * *"
    call_command("ensure_sweep_schedule")
    assert Schedule.objects.get(name="daily-sweep").cron == "0 5 * * *"
