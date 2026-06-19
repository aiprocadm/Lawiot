import re
from dataclasses import dataclass, field

import httpx

from ingestion.fetching import DEFAULT_TIMEOUT, MAX_RETRIES, USER_AGENT

IPS_BASE = "http://pravo.gov.ru/proxy/ips/"
_ND_RE = re.compile(r"nd=(\d+)")


@dataclass
class ResolveResult:
    candidates: list[str] = field(default_factory=list)
    note: str = ""


def _new_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.HTTPTransport(retries=MAX_RETRIES),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def resolve_nd(act, *, client: httpx.Client | None = None) -> ResolveResult:
    """Best-effort: попытаться найти кандидатов nd в ИПС по названию акта.

    ИПС-поиск нестабилен headless (stateful JS-фреймсет, часто 500) — поэтому
    пустой результат штатен: куратор введёт nd вручную. Любой сетевой/HTTP-сбой
    превращается в мягкий пустой результат, НЕ в исключение."""
    owns_client = client is None
    client = client or _new_client()
    try:
        resp = client.get(
            IPS_BASE, params={"searchlist": "", "intelsearch": act.title[:120]}
        )
        if resp.status_code != 200:
            return ResolveResult(note=f"ИПС вернул {resp.status_code}")
        body = resp.content.decode("cp1251", errors="replace")
        candidates = []
        for nd in _ND_RE.findall(body):
            if nd not in candidates:
                candidates.append(nd)
        note = "" if candidates else "кандидатов не найдено"
        return ResolveResult(candidates=candidates, note=note)
    except Exception as exc:  # best-effort: сбой → пустой результат
        return ResolveResult(note=f"ошибка резолва: {type(exc).__name__}")
    finally:
        if owns_client:
            client.close()
