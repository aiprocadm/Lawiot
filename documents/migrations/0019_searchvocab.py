from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0018_article_uniq_redaction_anchor"),
    ]

    operations = [
        # CREATE EXTENSION IF NOT EXISTS pg_trgm — до индекса с gin_trgm_ops.
        TrigramExtension(),
        migrations.CreateModel(
            name="SearchVocab",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("word", models.CharField(max_length=64, unique=True)),
                ("frequency", models.PositiveIntegerField(default=1)),
            ],
        ),
        migrations.AddIndex(
            model_name="searchvocab",
            index=GinIndex(fields=["word"], name="searchvocab_word_trgm", opclasses=["gin_trgm_ops"]),
        ),
    ]
