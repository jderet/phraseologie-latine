"""Co-authors of a version become roles in a project (choice of 21 September 2026).

Everyone who co-authored the translation of a project becomes a translator of that project;
the creator stays an editor without a row. The revisions of the old rows are dropped: the new
rows start their own history.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def carry_members(apps, schema_editor):
    """Each co-author of a version becomes a translator of its project."""
    VersionMember = apps.get_model("translations", "VersionMember")
    ProjectMember = apps.get_model("translations", "ProjectMember")
    seen = set()
    for old in VersionMember.objects.select_related("version").order_by("pk"):
        key = (old.version.project_id, old.user_id)
        if key in seen:
            continue
        seen.add(key)
        ProjectMember.objects.create(
            project_id=old.version.project_id,
            user_id=old.user_id,
            role="translator",
            invited_by_id=old.invited_by_id,
            status=old.status,
            invited_at=old.invited_at,
            decided_at=old.decided_at,
            is_hidden=old.is_hidden,
        )


def forget_old_members(apps, schema_editor):
    """The revisions, reports and events of the old rows go: their model no longer exists."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    content_type = ContentType.objects.filter(
        app_label="translations", model="versionmember"
    ).first()
    if content_type is None:
        return
    ids = list(
        apps.get_model("translations", "VersionMember").objects.values_list("pk", flat=True)
    )
    if not ids:
        return
    apps.get_model("activity", "Notification").objects.filter(
        event__content_type=content_type, event__object_id__in=ids
    ).delete()
    for label, name in (
        ("moderation", "Revision"),
        ("moderation", "Report"),
        ("moderation", "Comment"),
        ("moderation", "Vote"),
        ("activity", "Event"),
        ("activity", "Subscription"),
    ):
        apps.get_model(label, name).objects.filter(
            content_type=content_type, object_id__in=ids
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('translations', '0029_remove_variant_versions_and_proposals'),
        ('activity', '0004_alter_event_verb'),
        ('moderation', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ProjectMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_hidden', models.BooleanField(default=False, verbose_name='masqué')),
                ('role', models.CharField(choices=[('editor', 'éditeur'), ('translator', 'traducteur'), ('corrector', 'correcteur')], default='translator', max_length=10, verbose_name='rôle')),
                ('status', models.CharField(choices=[('invited', 'invité'), ('active', 'membre'), ('declined', 'invitation refusée'), ('removed', 'retiré')], default='invited', editable=False, max_length=10, verbose_name='statut')),
                ('invited_at', models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name='invité le')),
                ('decided_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='réponse le')),
            ],
            options={
                'verbose_name': 'rôle dans un projet',
                'verbose_name_plural': 'rôles dans un projet',
                'ordering': ['project', 'invited_at', 'pk'],
            },
        ),
        migrations.RemoveConstraint(
            model_name='versionmember',
            name='translations_one_membership',
        ),
        migrations.AddField(
            model_name='projectmember',
            name='invited_by',
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='invité par'),
        ),
        migrations.AddField(
            model_name='projectmember',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='members', to='translations.translationproject', verbose_name='projet'),
        ),
        migrations.AddField(
            model_name='projectmember',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='project_memberships', to=settings.AUTH_USER_MODEL, verbose_name='membre'),
        ),
        migrations.RunPython(carry_members, migrations.RunPython.noop),
        migrations.RunPython(forget_old_members, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='versionmember',
            name='invited_by',
        ),
        migrations.RemoveField(
            model_name='versionmember',
            name='user',
        ),
        migrations.RemoveField(
            model_name='versionmember',
            name='version',
        ),
        migrations.AddConstraint(
            model_name='projectmember',
            constraint=models.UniqueConstraint(fields=('project', 'user'), name='translations_one_membership'),
        ),
        migrations.DeleteModel(
            name='VersionMember',
        ),
    ]
