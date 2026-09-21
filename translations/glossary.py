"""Glossary of a project: agreed renderings of source terms, found and marked in the sentences.

Any active account proposes a term; the maintainers of the project or a reviewer adopt or reject
it. Terms are matched as whole words, whatever the case and the accents."""

import re
import unicodedata
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext

from accounts.roles import is_reviewer
from moderation.registry import can_view
from moderation.services import save_with_revision

from .models import GlossaryEntry, is_editor


def can_propose_term(user, project):
    return user.is_authenticated and user.is_active and not project.is_hidden


def can_decide_term(user, project):
    return (
        user.is_authenticated and user.is_active and (is_editor(user, project) or is_reviewer(user))
    )


def can_change_term(user, entry):
    """The maintainers of the project and reviewers change any term; its author, until decided."""
    if can_decide_term(user, entry.project):
        return True
    return (
        user.is_authenticated
        and user.pk == entry.author_id
        and entry.status == GlossaryEntry.Status.PROPOSED
    )


@transaction.atomic
def propose_term(entry, author):
    if not can_propose_term(author, entry.project):
        raise PermissionDenied
    entry.author = author
    # A term proposed by whoever may adopt it is adopted at once.
    if can_decide_term(author, entry.project):
        entry.status = GlossaryEntry.Status.ADOPTED
        entry.decided_by = author
    save_with_revision(entry, author)
    return entry


@transaction.atomic
def decide_term(entry, user, adopt):
    entry = GlossaryEntry.objects.select_for_update().select_related("project").get(pk=entry.pk)
    if not can_decide_term(user, entry.project):
        raise PermissionDenied
    status = GlossaryEntry.Status.ADOPTED if adopt else GlossaryEntry.Status.REJECTED
    if entry.status == status:
        return None
    entry.status = status
    entry.decided_by = user
    comment = gettext("Terme adopté") if adopt else gettext("Terme écarté")
    return save_with_revision(entry, user, comment=comment)


def visible_terms(user, project, statuses=(GlossaryEntry.Status.ADOPTED,)):
    entries = project.glossary.filter(status__in=statuses).select_related(
        "unit", "neologism", "project"
    )
    return [entry for entry in entries if can_view(user, entry)]


def fold(text):
    """Lower case without accents, one character for each character of the text, so that the
    positions found in the folded text are those of the text."""
    folded = []
    for char in text:
        base = unicodedata.normalize("NFD", char)[0].lower()
        folded.append(base if len(base) == 1 else char)
    return "".join(folded)


@dataclass(frozen=True)
class Found:
    start: int
    end: int
    entry: GlossaryEntry


def find_terms(text, entries):
    """Occurrences of the source terms in a text, longest terms first, without overlaps."""
    folded = fold(text)
    taken = []
    found = []
    for entry in sorted(entries, key=lambda entry: -len(entry.source_term)):
        term = fold(" ".join(entry.source_term.split()))
        if not term:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")
        for match in pattern.finditer(folded):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            found.append(Found(match.start(), match.end(), entry))
    return sorted(found, key=lambda item: item.start)


def marked_text(text, entries):
    """The sentence with the glossary terms marked, their Latin in a bubble; all escaped."""
    parts, position = [], 0
    for item in find_terms(text, entries):
        parts.append(format_html("{}", text[position : item.start]))
        parts.append(
            format_html(
                '<mark class="term" title="{}" data-use-latin="{}" data-mode="insert">{}</mark>',
                f"→ {item.entry.latin_term}",
                item.entry.latin_term,
                text[item.start : item.end],
            )
        )
        position = item.end
    parts.append(format_html("{}", text[position:]))
    return format_html_join("", "{}", ((part,) for part in parts))


def latin_present(latin, entry):
    """Whether the Latin of a sentence renders a term: each word of the Latin term appears,
    by its stem, since Latin inflects (« rēs pūblica » is found in « rem pūblicam »)."""
    words = re.findall(r"\w+", fold(latin))
    for term_word in re.findall(r"\w+", fold(entry.latin_term)):
        stem = term_word[:2] if len(term_word) <= 4 else term_word[: len(term_word) - 3]
        if not any(word.startswith(stem) for word in words):
            return False
    return True
