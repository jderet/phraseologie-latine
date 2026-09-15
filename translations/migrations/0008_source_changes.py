import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import F


def number_positions(apps, schema_editor):
    """Existing sentences keep their number as position: no text has changed yet."""
    segment = apps.get_model("translations", "Segment")
    segment.objects.update(position=F("order"))


class Migration(migrations.Migration):
    dependencies = [
        ("translations", "0007_change_proposals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="segment", name="translations_segment_order"),
        migrations.AddField(
            model_name="segment",
            name="position",
            field=models.PositiveIntegerField(default=0, editable=False, verbose_name="position"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="segment",
            name="order",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="numéro"),
        ),
        migrations.AddField(
            model_name="segment",
            name="added_in",
            field=models.PositiveIntegerField(
                default=0, editable=False, verbose_name="ajoutée au changement"
            ),
        ),
        migrations.AddField(
            model_name="segment",
            name="removed_in",
            field=models.PositiveIntegerField(
                blank=True, editable=False, null=True, verbose_name="retirée au changement"
            ),
        ),
        migrations.RunPython(number_positions, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="segment",
            options={
                "ordering": ["source_text", "position"],
                "verbose_name": "segment",
                "verbose_name_plural": "segments",
            },
        ),
        migrations.AlterModelOptions(
            name="translatedsegment",
            options={
                "ordering": ["version", "segment__position"],
                "verbose_name": "phrase traduite",
                "verbose_name_plural": "phrases traduites",
            },
        ),
        migrations.AlterModelOptions(
            name="stepsentence",
            options={
                "ordering": ["step", "segment__position"],
                "verbose_name": "phrase d’une étape",
                "verbose_name_plural": "phrases d’une étape",
            },
        ),
        migrations.AlterModelOptions(
            name="proposedsentence",
            options={
                "ordering": ["proposal", "segment__position"],
                "verbose_name": "phrase proposée",
                "verbose_name_plural": "phrases proposées",
            },
        ),
        migrations.AddConstraint(
            model_name="segment",
            constraint=models.UniqueConstraint(
                deferrable=models.Deferrable["DEFERRED"],
                fields=("source_text", "position"),
                name="translations_segment_position",
            ),
        ),
        migrations.AddConstraint(
            model_name="segment",
            constraint=models.CheckConstraint(
                condition=models.Q(("order__isnull", False), ("removed_in__isnull", True))
                | models.Q(("order__isnull", True), ("removed_in__isnull", False)),
                name="translations_segment_order_if_current",
            ),
        ),
        migrations.AddField(
            model_name="sourcetext",
            name="state",
            field=models.PositiveIntegerField(
                default=0, editable=False, verbose_name="état des phrases"
            ),
        ),
        migrations.AddField(
            model_name="versionstep",
            name="source_state",
            field=models.PositiveIntegerField(
                default=0, editable=False, verbose_name="état du texte source"
            ),
        ),
        migrations.CreateModel(
            name="SourceChange",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.PositiveIntegerField(verbose_name="numéro")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("insert", "ajout"),
                            ("edit", "modification"),
                            ("merge", "fusion"),
                            ("split", "scission"),
                        ],
                        max_length=10,
                        verbose_name="nature",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False, verbose_name="date"
                    ),
                ),
                (
                    "adopted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="adopté par",
                    ),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="auteur",
                    ),
                ),
                (
                    "source_text",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="changes",
                        to="translations.sourcetext",
                        verbose_name="texte source",
                    ),
                ),
            ],
            options={
                "verbose_name": "changement du texte source",
                "verbose_name_plural": "changements du texte source",
                "ordering": ["source_text", "number"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_text", "number"),
                        name="translations_source_change_number",
                    )
                ],
            },
        ),
    ]
