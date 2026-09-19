"""Subjects of a project, like issues: opened by any active account, closed or reopened by their
author, the creator of the project or a reviewer. Every change is recorded as a revision."""

import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext

from accounts.roles import is_reviewer
from activity.models import Verb
from activity.services import auto_follow, record
from moderation.registry import can_view
from moderation.services import save_with_revision

from .models import Topic, TranslationProject

REFERENCE = re.compile(r"(?<![\w&#/])#(\d{1,6})\b")


def can_open_topic(user, project):
    return user.is_authenticated and user.is_active and not project.is_hidden


def can_close_topic(user, topic):
    return (
        user.is_authenticated
        and user.is_active
        and (user.pk in (topic.author_id, topic.project.created_by_id) or is_reviewer(user))
    )


def clean_labels(labels):
    known = set(Topic.Label.values)
    return [label for label in Topic.Label.values if label in set(labels) & known]


@transaction.atomic
def open_topic(topic, author):
    project = TranslationProject.objects.select_for_update().get(pk=topic.project_id)
    if not can_open_topic(author, project):
        raise PermissionDenied
    if topic.segment_id and topic.segment.source_text_id != project.source_text_id:
        raise ValidationError(gettext("Cette phrase n’appartient pas au texte du projet."))
    last = project.topics.aggregate(last=Max("number"))["last"] or 0
    topic.number = last + 1
    topic.author = author
    topic.labels = clean_labels(topic.labels)
    save_with_revision(topic, author)
    auto_follow(author, topic)
    record(
        author,
        Verb.TOPIC_OPENED,
        topic,
        recipients=[project.created_by_id],
        mention_text=topic.body,
    )
    return topic


@transaction.atomic
def set_topic_status(topic, user, open_):
    topic = Topic.objects.select_for_update().select_related("project").get(pk=topic.pk)
    if not can_close_topic(user, topic):
        raise PermissionDenied
    if topic.is_open == open_:
        return None
    topic.status = Topic.Status.OPEN if open_ else Topic.Status.CLOSED
    topic.closed_at = None if open_ else timezone.now()
    topic.closed_by = None if open_ else user
    comment = gettext("Sujet rouvert") if open_ else gettext("Sujet fermé")
    revision = save_with_revision(topic, user, comment=comment)
    verb = Verb.TOPIC_REOPENED if open_ else Verb.TOPIC_CLOSED
    record(user, verb, topic, recipients=[topic.author_id])
    return revision


def linked_text(user, text, project):
    """The text of a topic or a message with « #3 » linked to the topic n° 3 of the project,
    when the reader may see it; everything else is escaped, and lines are kept."""
    numbers = {int(number) for number in REFERENCE.findall(text or "")}
    topics = {
        topic.number: topic
        for topic in project.topics.filter(number__in=numbers)
        if can_view(user, topic)
    }
    parts = []
    for line_number, line in enumerate((text or "").splitlines()):
        if line_number:
            parts.append(mark_safe("<br>"))  # a constant, never user input
        position = 0
        for match in REFERENCE.finditer(line):
            parts.append(format_html("{}", line[position : match.start()]))
            topic = topics.get(int(match.group(1)))
            if topic is None:
                parts.append(format_html("{}", match.group(0)))
            else:
                parts.append(
                    format_html(
                        '<a href="{}" title="{}">{}</a>',
                        topic.get_absolute_url(),
                        topic.title,
                        match.group(0),
                    )
                )
            position = match.end()
        parts.append(format_html("{}", line[position:]))
    return format_html_join("", "{}", ((part,) for part in parts))
