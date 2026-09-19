from django.db import migrations, models


class Migration(migrations.Migration):
    """Last part of the change of 19 September 2026: versions no longer declare a style, and the
    reference version gives way to the main version."""

    dependencies = [
        ("translations", "0022_main_versions"),
    ]

    operations = [
        migrations.RemoveField(model_name="translationversion", name="style"),
        migrations.RemoveField(model_name="translationversion", name="style_note"),
        migrations.RemoveField(model_name="translationproject", name="reference_version"),
        migrations.AddConstraint(
            model_name="translationversion",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("closed_at__isnull", True), ("variant_status__in", ["", "open"])),
                    models.Q(
                        ("closed_at__isnull", False),
                        ("variant_status__in", ["merged", "set_aside"]),
                    ),
                    _connector="OR",
                ),
                name="translations_version_closing",
            ),
        ),
    ]
