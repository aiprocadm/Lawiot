from django import forms

from documents.models import Document


class ManualImportForm(forms.Form):
    document = forms.ModelChoiceField(queryset=Document.objects.all(), label="Документ")
    paste_text = forms.CharField(
        widget=forms.Textarea, required=False, label="Вставить текст"
    )
    upload_file = forms.FileField(
        required=False, label="Или загрузить файл (.txt/.html)"
    )
    content_type = forms.ChoiceField(
        choices=[("text/plain", "Текст"), ("text/html", "HTML")],
        initial="text/plain",
        label="Тип содержимого",
    )
    source_url = forms.URLField(
        required=False, label="URL источника", assume_scheme="https"
    )
    redaction_date = forms.DateField(required=False, label="Дата редакции (Действует с)")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("paste_text") and not cleaned.get("upload_file"):
            raise forms.ValidationError("Вставьте текст или загрузите файл.")
        return cleaned
