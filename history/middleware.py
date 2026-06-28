from datetime import timedelta

from django.apps import apps
from django.utils import timezone

# Не пишем чаще, чем раз в это окно на пару (пользователь, акт). Раньше КАЖДЫЙ
# просмотр акта (в т.ч. обновление страницы) шёл UPDATE — амплификация записи.
# «Последний просмотр» при этом остаётся практически точным.
_WRITE_THROTTLE = timedelta(minutes=1)


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
        # Достаём только id (вью документа уже загрузил сам объект — полный SELECT
        # здесь был бы лишним).
        doc_id = document_model.objects.filter(slug=slug).values_list("id", flat=True).first()
        if doc_id is None:
            return
        now = timezone.now()
        last_viewed = (
            view_history.objects.filter(user=user, document_id=doc_id)
            .values_list("viewed_at", flat=True)
            .first()
        )
        if last_viewed is None:
            view_history.objects.create(user=user, document_id=doc_id, viewed_at=now)
        elif now - last_viewed >= _WRITE_THROTTLE:
            view_history.objects.filter(user=user, document_id=doc_id).update(viewed_at=now)
