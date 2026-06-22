from assistant.prompts import SYSTEM_PROMPT, build_user_content
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
