"""Discovery verification gate: fetch doc_itself&nd=X&print=1, parse, report.
Pure — no Django/DB needed. Run with the repo venv from repo root.
Usage: python verify_nd.py <nd> [<nd> ...]
"""
import sys

sys.path.insert(0, ".")

from ingestion.fetching import fetch  # noqa: E402
from ingestion.parsing import parse_document  # noqa: E402

IPS = "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd={nd}&print=1"


def report(nd: str, doc_type: str = "code") -> None:
    url = IPS.format(nd=nd)
    try:
        res = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"nd={nd}: FETCH ERROR {type(e).__name__}: {e}")
        return
    pd = parse_document(res.content, res.content_type, doc_type=doc_type)
    arts = [a for a in pd.articles if a.kind == "article"]
    secs = [a for a in pd.articles if a.kind == "section"]
    chs = [a for a in pd.articles if a.kind == "chapter"]
    orphans = [a for a in arts if a.parent_order is None and (secs or chs)]
    print(f"nd={nd}  bytes={len(res.content)}  ctype={res.content_type!r}")
    print(f"  title:   {pd.title!r}")
    print(f"  number:  {pd.detected_number!r}  red_date: {pd.detected_redaction_date}")
    print(f"  nodes:   sections={len(secs)} chapters={len(chs)} articles={len(arts)} orphans={len(orphans)}")
    head = [ln for ln in pd.full_text.splitlines() if ln][:8]
    print("  head:    " + " | ".join(head))
    print()


if __name__ == "__main__":
    for nd in sys.argv[1:]:
        report(nd)
