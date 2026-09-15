"""Existing challenges are about the first step of their version, created from its text."""

from django.db import migrations


def link_challenges(apps, schema_editor):
    Challenge = apps.get_model("justifications", "Challenge")
    VersionStep = apps.get_model("translations", "VersionStep")
    for challenge in Challenge.objects.filter(step__isnull=True).select_related(
        "translated_segment"
    ):
        step = (
            VersionStep.objects.filter(version_id=challenge.translated_segment.version_id)
            .order_by("-number")
            .first()
        )
        if step is not None:
            challenge.step = step
            challenge.save(update_fields=["step"])


class Migration(migrations.Migration):
    dependencies = [
        ("justifications", "0006_challenge_step"),
        ("translations", "0005_first_steps"),
    ]

    operations = [
        migrations.RunPython(link_challenges, migrations.RunPython.noop),
    ]
