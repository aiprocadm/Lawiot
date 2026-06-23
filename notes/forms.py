from django import forms

from documents.models import Document
from notes.models import Note


class NoteForm(forms.ModelForm):
    document = forms.ModelChoiceField(
        queryset=Document.objects.order_by("title"), label="Акт", empty_label="— выберите акт —"
    )

    class Meta:
        model = Note
        fields = ["document", "article_number", "text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3})}
