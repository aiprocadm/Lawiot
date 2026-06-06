from datetime import date

from django.core.management.base import BaseCommand

from documents.models import Article, Document, Redaction


class Command(BaseCommand):
    help = "Создаёт демонстрационный акт для ручной приёмки."

    def handle(self, *args, **options):
        doc, _ = Document.objects.get_or_create(
            slug="tk-rf-demo",
            defaults={
                "doc_type": Document.DocType.CODE,
                "title": "Трудовой кодекс Российской Федерации (демо)",
                "official_number": "197-ФЗ",
                "issuing_body": "Федеральное Собрание РФ",
                "status": Document.Status.IN_FORCE,
            },
        )
        redaction, created = Redaction.objects.get_or_create(
            document=doc, redaction_date=date(2024, 1, 1),
            defaults={"full_text": "Демонстрационная редакция."},
        )
        if created:
            Article.objects.create(
                redaction=redaction,
                kind=Article.Kind.ARTICLE,
                number="81",
                title="Расторжение трудового договора по инициативе работодателя",
                text="Трудовой договор может быть расторгнут работодателем в случаях...",
                order=1,
            )
        redaction.publish()
        self.stdout.write(self.style.SUCCESS("Демо-акт создан и опубликован."))
