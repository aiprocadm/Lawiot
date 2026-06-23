from django.apps import apps
from django.utils import timezone


class RecordViewMiddleware:
    """Фиксирует просмотр акта (document_detail) авторизованным пользователем.

    Реализовано middleware'ом, чтобы не трогать вью документа. Пишет только на
    успешный просмотр страницы акта; одна строка на (пользователь, акт),
    обновляется при повторном заходе.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, "resolver_match", None)
        user = getattr(request, "user", None)
        if (
            match is not None
            and match.url_name == "document_detail"
            and response.status_code == 200
            and getattr(user, "is_authenticated", False)
        ):
            self._record(user, match.kwargs.get("slug"))
        return response

    @staticmethod
    def _record(user, slug):
        if not slug:
            return
        document_model = apps.get_model("documents", "Document")
        view_history = apps.get_model("history", "ViewHistory")
        document = document_model.objects.filter(slug=slug).first()
        if document is None:
            return
        view_history.objects.update_or_create(
            user=user, document=document, defaults={"viewed_at": timezone.now()}
        )
