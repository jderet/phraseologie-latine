"""A first step for each existing version, so that the public keeps seeing its text."""

from django.db import migrations

MESSAGE = "État de la version à la mise en place des étapes"


def create_first_steps(apps, schema_editor):
    TranslationVersion = apps.get_model("translations", "TranslationVersion")
    TranslatedSegment = apps.get_model("translations", "TranslatedSegment")
    VersionStep = apps.get_model("translations", "VersionStep")
    StepSentence = apps.get_model("translations", "StepSentence")
    for version in TranslationVersion.objects.filter(steps__isnull=True):
        # A sentence hidden after a report was not shown to the public: it stays out.
        sentences = list(
            TranslatedSegment.objects.filter(version=version, is_hidden=False).exclude(text="")
        )
        if not sentences:
            continue
        created_at = max(sentence.updated_at for sentence in sentences)
        if version.published_at and version.published_at > created_at:
            created_at = version.published_at
        step = VersionStep.objects.create(
            version=version,
            number=1,
            message=MESSAGE,
            author_id=version.author_id,
            during_draft=version.state == "draft",
            created_at=created_at,
        )
        StepSentence.objects.bulk_create(
            StepSentence(step=step, segment_id=sentence.segment_id, text=sentence.text)
            for sentence in sentences
        )


class Migration(migrations.Migration):
    dependencies = [
        ("translations", "0004_translatedsegment_written_by_and_more"),
    ]

    operations = [
        migrations.RunPython(create_first_steps, migrations.RunPython.noop),
    ]
