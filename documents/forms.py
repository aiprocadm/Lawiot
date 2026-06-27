from django import forms

from documents.models import Document


class ManualImportForm(forms.Form):
    # Кодексы бывают объёмными (~9 МБ), но не безразмерными — потолок против
    # случайной загрузки гигантского файла (OOM при парсинге).
    MAX_UPLOAD_BYTES = 20 * 1024 * 1024
    ALLOWED_EXTENSIONS = (".txt", ".html", ".htm")

    document = forms.ModelChoiceField(queryset=Document.objects.all(), label="Документ")
    paste_text = forms.CharField(widget=forms.Textarea, required=False, label="Вставить текст")
    upload_file = forms.FileField(required=False, label="Или загрузить файл (.txt/.html)")
    content_type = forms.ChoiceField(
        choices=[("text/plain", "Текст"), ("text/html", "HTML")],
        initial="text/plain",
        label="Тип содержимого",
    )
    source_url = forms.URLField(required=False, label="URL источника", assume_scheme="https")
    redaction_date = forms.DateField(required=False, label="Дата редакции (Действует с)")

    def clean_upload_file(self):
        upload = self.cleaned_data.get("upload_file")
        if not upload:
            return upload
        name = (upload.name or "").lower()
        if not name.endswith(self.ALLOWED_EXTENSIONS):
            raise forms.ValidationError("Допустимы только файлы .txt или .html.")
        if upload.size and upload.size > self.MAX_UPLOAD_BYTES:
            mb = self.MAX_UPLOAD_BYTES // (1024 * 1024)
            raise forms.ValidationError(f"Файл больше {mb} МБ.")
        return upload

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("paste_text") and not cleaned.get("upload_file"):
            raise forms.ValidationError("Вставьте текст или загрузите файл.")
        return cleaned
