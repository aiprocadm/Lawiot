from assistant.prompts import MAX_INPUT_CHARS, SYSTEM_PROMPT, build_user_content, cap_text
from assistant.retrieval import RetrievedArticle


def test_system_prompt_has_guardrails():
    assert "не придумывай" in SYSTEM_PROMPT
    assert "консультаци" in SYSTEM_PROMPT
    assert "Статья" in SYSTEM_PROMPT


def test_build_user_content_includes_question_and_texts():
    arts = [
        RetrievedArticle(
            document_title="Трудовой кодекс",
            article_label="Статья 127",
            anchor="st-127",
            url="/doc/tk/#st-127",
            text="текст про отпуск при увольнении",
            rank=0.5,
        )
    ]
    content = build_user_content("положена ли компенсация отпуска?", arts)

    assert "положена ли компенсация отпуска?" in content
    assert "текст про отпуск при увольнении" in content
    assert "Статья 127" in content


def test_cap_text_passes_short_text_through():
    assert cap_text("короткий текст") == "короткий текст"
    assert cap_text("") == ""
    assert cap_text(None) == ""


def test_cap_text_truncates_overlong_text():
    long = "а" * (MAX_INPUT_CHARS + 5000)
    capped = cap_text(long)
    assert len(capped) < len(long)
    assert capped.startswith("а" * MAX_INPUT_CHARS)
    assert "сокращён" in capped


def test_build_user_content_caps_article_text():
    arts = [
        RetrievedArticle(
            document_title="ТК",
            article_label="Статья 1",
            anchor="st-1",
            url="/doc/tk/#st-1",
            text="я" * (MAX_INPUT_CHARS + 3000),
            rank=0.1,
        )
    ]
    content = build_user_content("вопрос", arts)
    assert "сокращён" in content
    # Гигантский текст не утёк целиком в сообщение модели.
    assert content.count("я") <= MAX_INPUT_CHARS + 5
