import re
from dataclasses import dataclass, field

import httpx

from ingestion.fetching import managed_client

# http (не https) намеренно: pravo.gov.ru не обслуживает TLS (проверено
# 2026-06-29: http → 200, https → отказ соединения). https сломал бы ингест.
IPS_BASE = "http://pravo.gov.ru/proxy/ips/"
_ND_RE = re.compile(r"nd=(\d+)")
# ИПС-поиск обрезает длинные запросы; наблюдаемый практический предел — 120 символов.
_IPS_QUERY_MAX_LEN = 120


@dataclass
class ResolveResult:
    candidates: list[str] = field(default_factory=list)
    note: str = ""


def resolve_nd(act, *, client: httpx.Client | None = None) -> ResolveResult:
    """Best-effort: попытаться найти кандидатов nd в ИПС по названию акта.

    ИПС-поиск нестабилен headless (stateful JS-фреймсет, часто 500) — поэтому
    пустой результат штатен: куратор введёт nd вручную. Любой сетевой/HTTP-сбой
    превращается в мягкий пустой результат, НЕ в исключение."""
    with managed_client(client) as client:
        try:
            resp = client.get(
                IPS_BASE,
                params={"searchlist": "", "intelsearch": act.title[:_IPS_QUERY_MAX_LEN]},
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
