from ingestion.parsing import parse_points


def test_top_level_points():
    nodes = parse_points("1. Первый пункт.\n2. Второй пункт.")
    assert [(n.kind, n.number) for n in nodes] == [("point", "1"), ("point", "2")]
    assert nodes[0].text == "Первый пункт."


def test_subpoint_nests_under_parent_point():
    nodes = parse_points("1. Общие положения.\n1.1. Первый подпункт.")
    parent, child = nodes[0], nodes[1]
    assert child.kind == "point" and child.number == "1.1"
    assert child.parent_order == parent.order


def test_appendix_is_container_for_following_points():
    nodes = parse_points("Приложение 1\nк постановлению\n1. Пункт приложения.")
    assert nodes[0].kind == "appendix" and nodes[0].number == "1"
    point = next(n for n in nodes if n.kind == "point")
    assert point.parent_order == nodes[0].order


def test_section_inside_appendix_reuses_codex_rules():
    nodes = parse_points("Приложение 1\nРаздел I. Общие положения\n1. Пункт.")
    assert [n.kind for n in nodes] == ["appendix", "section", "point"]
    appendix, section, point = nodes
    assert section.parent_order == appendix.order
    assert point.parent_order == section.order


def test_flat_act_without_points_yields_nothing():
    assert parse_points("Краткий приказ без нумерации, просто текст.") == []


def test_decimal_in_prose_is_not_a_point():
    assert parse_points("Срок 1 год.\nОплата 2.5 ставки месяца.") == []


def test_utverzhdeno_marks_appendix():
    nodes = parse_points("УТВЕРЖДЕНО\nпостановлением Правительства\n1. Пункт.")
    assert nodes[0].kind == "appendix"
    assert next(n for n in nodes if n.kind == "point").parent_order == nodes[0].order
