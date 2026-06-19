import json
from datetime import date
from pathlib import Path

from ingestion.publication import PublicationDoc, doc_type_for, parse_item

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_raw" / "publication_mintrud_page1.json"


def _items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]


def test_parse_item_maps_fields():
    doc = parse_item(_items()[0])
    assert isinstance(doc, PublicationDoc)
    assert doc.eo_number == "0001202606090026"
    assert doc.number == "200н"
    assert doc.document_date == date(2026, 5, 8)
    assert doc.doc_type == "order"  # приказ
    assert doc.pdf_url.endswith("eoNumber=0001202606090026")


def test_doc_type_for_known_and_unknown():
    assert doc_type_for("2dddb344-d3e2-4785-a899-7aa12bd47b6f") == "order"
    assert doc_type_for("fd5a8766-f6fd-4ac2-8fd9-66f414d314ac") == "decree"
    assert doc_type_for("00000000-0000-0000-0000-000000000000") == "other"
