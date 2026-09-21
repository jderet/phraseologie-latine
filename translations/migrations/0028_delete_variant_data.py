"""Delete the variant-copies and the change proposals (choice of 21 September 2026).

A variant used to be a copy of a whole translation, sent to the maintainers as a change
proposal. Variants are now other readings of one sentence (``SegmentVariant``), so the copies,
their proposals and everything attached to them go away, generic rows included.
"""

from django.db import migrations

# Contents whose rows are deleted with the versions they belong to.
GENERIC = (
    ("translations", "changeproposal"),
    ("translations", "proposedsentence"),
    ("translations", "proposalreview"),
    ("translations", "translationversion"),
    ("translations", "translatedsegment"),
    ("translations", "versionstep"),
    ("translations", "stepsentence"),
    ("translations", "versionmember"),
    ("translations", "sentencecomment"),
    ("justifications", "justification"),
    ("justifications", "evidence"),
    ("justifications", "challenge"),
)


def _forget(apps, deleted):
    """Remove the revisions, events, reports and messages that point at deleted contents."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    models = [
        apps.get_model("moderation", "Revision"),
        apps.get_model("moderation", "Report"),
        apps.get_model("moderation", "Comment"),
        apps.get_model("moderation", "Vote"),
        apps.get_model("activity", "Event"),
        apps.get_model("activity", "Subscription"),
    ]
    Notification = apps.get_model("activity", "Notification")
    for (app_label, model_name), ids in deleted.items():
        if not ids:
            continue
        content_type = ContentType.objects.filter(app_label=app_label, model=model_name).first()
        if content_type is None:
            continue
        Notification.objects.filter(
            event__content_type=content_type, event__object_id__in=ids
        ).delete()
        for model in models:
            model.objects.filter(content_type=content_type, object_id__in=ids).delete()


def delete_variants(apps, schema_editor):
    Version = apps.get_model("translations", "TranslationVersion")
    versions = list(Version.objects.exclude(variant_status="").values_list("pk", flat=True))
    proposals = apps.get_model("translations", "ChangeProposal").objects.all()
    proposal_ids = list(proposals.values_list("pk", flat=True))
    proposed = apps.get_model("translations", "ProposedSentence").objects.all()
    reviews = apps.get_model("translations", "ProposalReview").objects.all()
    deleted = {
        ("translations", "proposedsentence"): list(proposed.values_list("pk", flat=True)),
        ("translations", "proposalreview"): list(reviews.values_list("pk", flat=True)),
        ("translations", "changeproposal"): proposal_ids,
    }
    reviews.delete()
    proposed.delete()
    proposals.delete()
    if versions:
        segments = apps.get_model("translations", "TranslatedSegment").objects.filter(
            version_id__in=versions
        )
        steps = apps.get_model("translations", "VersionStep").objects.filter(
            version_id__in=versions
        )
        justifications = apps.get_model("justifications", "Justification").objects.filter(
            translated_segment__version_id__in=versions
        )
        challenges = apps.get_model("justifications", "Challenge").objects.filter(
            translated_segment__version_id__in=versions
        )
        evidences = apps.get_model("justifications", "Evidence").objects.filter(
            justification__in=justifications
        )
        members = apps.get_model("translations", "VersionMember").objects.filter(
            version_id__in=versions
        )
        comments = apps.get_model("translations", "SentenceComment").objects.filter(
            version_id__in=versions
        )
        step_sentences = apps.get_model("translations", "StepSentence").objects.filter(
            step__version_id__in=versions
        )
        deleted.update(
            {
                ("justifications", "evidence"): list(evidences.values_list("pk", flat=True)),
                ("justifications", "justification"): list(
                    justifications.values_list("pk", flat=True)
                ),
                ("justifications", "challenge"): list(challenges.values_list("pk", flat=True)),
                ("translations", "translatedsegment"): list(
                    segments.values_list("pk", flat=True)
                ),
                ("translations", "stepsentence"): list(
                    step_sentences.values_list("pk", flat=True)
                ),
                ("translations", "versionstep"): list(steps.values_list("pk", flat=True)),
                ("translations", "versionmember"): list(members.values_list("pk", flat=True)),
                ("translations", "sentencecomment"): list(comments.values_list("pk", flat=True)),
                ("translations", "translationversion"): versions,
            }
        )
        evidences.delete()
        challenges.delete()
        justifications.delete()
        comments.delete()
        members.delete()
        step_sentences.delete()
        steps.delete()
        apps.get_model("translations", "IgnoredAlert").objects.filter(
            version_id__in=versions
        ).delete()
        apps.get_model("activity", "Star").objects.filter(version_id__in=versions).delete()
        segments.delete()
        Version.objects.filter(pk__in=versions).delete()
    _forget(apps, deleted)


class Migration(migrations.Migration):
    dependencies = [
        ("translations", "0027_sourcetext_author_birth_year"),
        ("activity", "0003_event_variant_set_aside"),
        ("justifications", "0001_initial"),
        ("moderation", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(delete_variants, migrations.RunPython.noop)]
