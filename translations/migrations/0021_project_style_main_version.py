import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """First part of the change of 19 September 2026: the style and the main version belong to
    the project, the other versions become variants."""

    dependencies = [
        ("translations", "0020_personal_memory"),
    ]

    operations = [
        migrations.AddField(
            model_name="translationproject",
            name="style",
            field=models.CharField(
                choices=[
                    ("classical", "classique, sans modèle particulier"),
                    ("ciceronian", "cicéronien"),
                    ("caesarian", "césarien"),
                    ("sallustian", "sallustien"),
                    ("livian", "livien"),
                    ("senecan", "sénéquien"),
                    ("tacitean", "tacitéen"),
                    ("plinian", "plinien (Pline le Jeune)"),
                    ("late", "latin tardif et chrétien"),
                    ("humanist", "humaniste"),
                    ("contemporary", "latin vivant contemporain"),
                ],
                default="classical",
                max_length=20,
                verbose_name="style visé",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="translationproject",
            name="style_note",
            field=models.CharField(
                blank=True,
                help_text="Facultatif, par exemple : « Cicéron des lettres à Atticus ».",
                max_length=200,
                verbose_name="précision sur le style",
            ),
        ),
        migrations.AddField(
            model_name="translationproject",
            name="main_version",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="translations.translationversion",
                verbose_name="traduction principale",
            ),
        ),
        migrations.AddField(
            model_name="translationversion",
            name="variant_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "traduction principale"),
                    ("open", "variante ouverte"),
                    ("merged", "variante fusionnée"),
                    ("set_aside", "variante écartée"),
                ],
                default="open",
                editable=False,
                max_length=10,
                verbose_name="statut de la variante",
            ),
        ),
        migrations.AddField(
            model_name="translationversion",
            name="closed_at",
            field=models.DateTimeField(
                blank=True, editable=False, null=True, verbose_name="close le"
            ),
        ),
        migrations.AddField(
            model_name="changeproposal",
            name="from_version",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sent_proposals",
                to="translations.translationversion",
                verbose_name="variante d’origine",
            ),
        ),
    ]
