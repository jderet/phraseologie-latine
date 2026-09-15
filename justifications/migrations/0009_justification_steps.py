"""Existing justifications came out with the first step of their version."""

from django.db import migrations


def link_justifications(apps, schema_editor):
    Justification = apps.get_model("justifications", "Justification")
    VersionStep = apps.get_model("translations", "VersionStep")
    for justification in Justification.objects.filter(step__isnull=True).select_related(
        "translated_segment"
    ):
        step = (
            VersionStep.objects.filter(version_id=justification.translated_segment.version_id)
            .order_by("number")
            .first()
        )
        if step is not None:
            justification.step = step
            justification.save(update_fields=["step"])


class Migration(migrations.Migration):
    dependencies = [
        ("justifications", "0008_justification_step"),
        ("translations", "0005_first_steps"),
    ]

    operations = [
        migrations.RunPython(link_justifications, migrations.RunPython.noop),
    ]
