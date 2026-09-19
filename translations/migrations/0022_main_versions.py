from django.db import migrations
from django.utils import timezone


def choose_main_versions(apps, schema_editor):
    """Each project keeps one main version and takes its style; the others become variants.

    The main version is the reference version, or else the first published, or else the oldest.
    A creator who is not the author of the main version becomes one of its co-authors. A project
    without any version gets an empty main version, written by its creator.
    """
    Project = apps.get_model("translations", "TranslationProject")
    Version = apps.get_model("translations", "TranslationVersion")
    Member = apps.get_model("translations", "VersionMember")
    for project in Project.objects.all():
        versions = Version.objects.filter(project=project)
        main = None
        if project.reference_version_id:
            main = versions.filter(pk=project.reference_version_id).first()
        if main is None:
            main = versions.filter(state="published").order_by("published_at", "pk").first()
        if main is None:
            main = versions.order_by("created_at", "pk").first()
        if main is None:
            main = Version.objects.create(
                project=project,
                author_id=project.created_by_id,
                style=getattr(project, "style", "classical") or "classical",
                variant_status="",
            )
        else:
            main.variant_status = ""
            main.save(update_fields=["variant_status"])
        project.main_version = main
        project.style = main.style
        project.style_note = main.style_note
        project.save(update_fields=["main_version", "style", "style_note"])
        if project.created_by_id != main.author_id:
            Member.objects.update_or_create(
                version=main,
                user_id=project.created_by_id,
                defaults={
                    "status": "active",
                    "invited_by_id": main.author_id,
                    "decided_at": timezone.now(),
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("translations", "0021_project_style_main_version"),
    ]

    operations = [
        migrations.RunPython(choose_main_versions, migrations.RunPython.noop),
    ]
