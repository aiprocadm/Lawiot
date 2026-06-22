from django import forms

from documents.models import Document


class SearchForm(forms.Form):
    q = forms.CharField(label="Запрос", required=False)
    doc_type = forms.ChoiceField(
        label="Тип",
        required=False,
        choices=[("", "Все типы")] + list(Document.DocType.choices),
    )
    status = forms.ChoiceField(
        label="Статус",
        required=False,
        choices=[("", "Любой статус")] + list(Document.Status.choices),
    )
    issuing_body = forms.CharField(label="Орган", required=False)
    date_from = forms.DateField(
        label="Дата с",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label="Дата по",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    sort = forms.ChoiceField(
        label="Сортировка",
        required=False,
        choices=[
            ("relevance", "По релевантности"),
            ("date", "По дате (новые первыми)"),
        ],
        initial="relevance",
    )
