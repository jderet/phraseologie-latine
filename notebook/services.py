"""What a reader keeps in a private notebook, and how it shows in the texts the reader reads."""

from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext

from justifications.services import corpus_evidence

from .models import Highlight, PassageList, PassageListEntry, PrivateNote

MAX_LISTS = 100


def _check_user(user):
    if not (user.is_authenticated and user.is_active):
        raise PermissionDenied


@transaction.atomic
def add_highlight(user, words, color=Highlight.Color.YELLOW):
    """Highlight words of the corpus, given by their identifiers, in one of a few colours."""
    _check_user(user)
    if color not in Highlight.Color.values:
        raise ValidationError(gettext("Choisissez une couleur."), code="color")
    evidence = corpus_evidence(words)
    highlight = Highlight.objects.create(
        owner=user, passage=evidence.tokens[0].passage, color=color
    )
    highlight.tokens.set(evidence.tokens)
    return highlight


@transaction.atomic
def add_private_note(user, words, text):
    """A note about words of the corpus, seen by its author only."""
    _check_user(user)
    text = text.strip()
    if not text:
        raise ValidationError(gettext("Écrivez la note."), code="empty")
    evidence = corpus_evidence(words)
    note = PrivateNote.objects.create(owner=user, passage=evidence.tokens[0].passage, text=text)
    note.tokens.set(evidence.tokens)
    return note


@transaction.atomic
def add_to_list(user, passage, name):
    """Put a passage in a named list of the reader, created if needed."""
    _check_user(user)
    name = " ".join(name.split())[:100]
    if not name:
        raise ValidationError(gettext("Nommez la liste."), code="empty")
    passage_list = PassageList.objects.filter(owner=user, name=name).first()
    if passage_list is None:
        if user.passage_lists.count() >= MAX_LISTS:
            raise ValidationError(
                gettext("Un carnet compte au plus %(limit)d listes.") % {"limit": MAX_LISTS},
                code="too_many_lists",
            )
        passage_list = PassageList.objects.create(owner=user, name=name)
    entry, _created = PassageListEntry.objects.get_or_create(
        passage_list=passage_list, passage=passage
    )
    return entry


def delete_notebook(user):
    """Delete everything a reader kept: the notebook is personal data, not a contribution."""
    Highlight.objects.filter(owner=user).delete()
    PrivateNote.objects.filter(owner=user).delete()
    PassageList.objects.filter(owner=user).delete()


@dataclass
class NotebookMark:
    """A highlight or a private note drawn among the words of a page, for its owner only."""

    item: object
    words: list
    # Drawn closest to the word, under the lines of the phraseology.
    track: int = -1

    @property
    def key(self):
        prefix = "h" if isinstance(self.item, Highlight) else "n"
        return f"{prefix}_{self.item.pk}"

    @property
    def css(self):
        if isinstance(self.item, Highlight):
            return f"hl hl-{self.item.color}"
        return "pn"


def notebook_marks(user, passages, token_ids):
    """The highlights and private notes of the user beginning in these passages."""
    if not user.is_authenticated:
        return []
    marks = []
    for model in (Highlight, PrivateNote):
        items = {item.pk: item for item in model.objects.filter(owner=user, passage__in=passages)}
        column = f"{model._meta.model_name}_id"
        rows = (
            model.tokens.through.objects.filter(**{f"{column}__in": list(items)})
            .order_by("token__position")
            .values_list(column, "token_id")
        )
        found = defaultdict(list)
        for pk, token_id in rows:
            if token_id in token_ids:
                found[pk].append(token_id)
        marks += [NotebookMark(items[pk], words) for pk, words in found.items()]
    return marks
