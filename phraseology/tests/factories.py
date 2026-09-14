"""Helpers to create phraseology contents in tests."""

from justifications.services import corpus_evidence
from phraseology.models import Unit
from phraseology.services import create_unit


def evidence(*tokens):
    """A corpus attestation as chosen in a form, from its words."""
    return corpus_evidence(",".join(str(token.pk) for token in tokens))


def make_unit(user, tokens, reference_form="consilium capere", definition="prendre une décision"):
    return create_unit(Unit(reference_form=reference_form), user, definition, [evidence(*tokens)])


def set_status(unit, status):
    Unit.objects.filter(pk=unit.pk).update(status=status)
    unit.refresh_from_db()
    return unit
