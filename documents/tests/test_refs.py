from documents.refs import linkify_internal_refs


def test_links_ref_when_anchor_present():
    html = linkify_internal_refs("в соответствии со статьёй 72 настоящего Кодекса", {"st-72"})
    assert '<a href="#st-72">статьёй 72</a>' in html


def test_no_link_when_anchor_absent():
    html = linkify_internal_refs("см. статью 999", {"st-72"})
    assert "<a" not in html
    assert "статью 999" in html


def test_escapes_html():
    html = linkify_internal_refs("текст <b>жирный</b> и <script>", {"st-1"})
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
    assert "<script>" not in html


def test_dotted_number_anchor():
    html = linkify_internal_refs("согласно статье 312.1", {"st-312-1"})
    assert 'href="#st-312-1"' in html


def test_paragraphs_and_breaks_preserved():
    html = linkify_internal_refs("абзац один\nстрока два\n\nабзац два", set())
    assert html.count("<p>") == 2
    assert "<br>" in html


def test_high_precision_no_bare_number():
    # «и 81» без префикса стать/ст не линкуется (высокая точность)
    html = linkify_internal_refs("статьями 72 и 81", {"st-72", "st-81"})
    assert 'href="#st-72"' in html
    assert 'href="#st-81"' not in html
