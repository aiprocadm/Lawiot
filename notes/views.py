from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from notes.forms import NoteForm
from notes.models import Note


@login_required
def note_list(request):
    """Заметки пользователя + форма добавления."""
    if request.method == "POST":
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.user = request.user
            note.save()
            return redirect("note_list")
    else:
        form = NoteForm()
    notes = Note.objects.filter(user=request.user).select_related("document")
    return render(request, "notes/note_list.html", {"notes": notes, "form": form})


@login_required
@require_POST
def note_delete(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    note.delete()
    return redirect("note_list")
