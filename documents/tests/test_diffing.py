from types import SimpleNamespace

from documents.diffing import diff_articles


def art(number, text):
    return SimpleNamespace(number=number, text=text)


def test_diff_detects_added_removed_changed_same():
    current = [art("1", "старый текст"), art("2", "без изменений"), art("9", "удалят")]
    draft = [art("1", "новый текст"), art("2", "без изменений"), art("3", "новая")]
    by_num = {d.number: d for d in diff_articles(current, draft)}
    assert by_num["1"].status == "changed"
    assert by_num["2"].status == "same"
    assert by_num["3"].status == "added"
    assert by_num["9"].status == "removed"


def test_changed_article_has_plus_and_minus_lines():
    [d] = diff_articles([art("1", "было")], [art("1", "стало")])
    tags = {tag for tag, _ in d.lines}
    assert "-" in tags and "+" in tags
