"""Сохранение смысла входящих связей при удалении документа-цели.
До обнуления to_document (SET_NULL) переносим номер цели в raw_citation,
чтобы ссылка деградировала во «вне корпуса», а не теряла информацию."""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from documents.models import Document, Link


@receiver(pre_delete, sender=Document)
def preserve_incoming_citations(sender, instance, **kwargs):
    Link.objects.filter(to_document=instance, raw_citation="").update(
        raw_citation=instance.official_number or instance.title[:200]
    )
