"""Helpers to create phraseology contents in tests."""

from corpus.models import AnalysisLayer, Author, Edition, Passage, Token, TokenAnalysis, Work
from corpus.text import normalize
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


def make_outside_passage(words, reference="1"):
    """A passage of a work outside the core of the corpus (Seneca's tragedies)."""
    author, _created = Author.objects.get_or_create(
        cts_id="phi1017",
        defaults={
            "name_fr": "Sénèque",
            "name_en": "Seneca",
            "latin_name": "L. Annaeus Seneca",
            "abbreviation": "Sen.",
            "birth_year": -4,
        },
    )
    work, _created = Work.objects.get_or_create(
        cts_urn="urn:cts:latinLit:phi1017.phi001",
        defaults={"author": author, "title": "Hercules Furens", "abbreviation": "Herc. F."},
    )
    edition, _created = Edition.objects.get_or_create(
        work=work,
        is_current=True,
        defaults={
            "cts_urn": "urn:cts:latinLit:phi1017.phi001.perseus-lat2",
            "source": "Perseus",
            "source_path": "data/phi1017/phi001/phi1017.phi001.perseus-lat2.xml",
            "source_version": "a" * 40,
            "license": "CC BY-SA 4.0",
        },
    )
    passage = Passage.objects.create(
        edition=edition,
        order=edition.passages.count() + 1,
        reference=reference,
        text=" ".join(words),
    )
    start = edition.tokens.count()
    tokens = [
        Token.objects.create(
            edition=edition,
            passage=passage,
            position=start + index,
            form=word.strip(".,"),
            norm=normalize(word.strip(".,")),
            after=word[len(word.strip(".,")) :] + " ",
        )
        for index, word in enumerate(words)
    ]
    return passage, tokens


def make_layer():
    return AnalysisLayer.objects.create(tool="LatinCy test", tool_version="1.0", is_default=True)


def analyze(layer, token, lemma, deprel="ROOT", head=None):
    return TokenAnalysis.objects.create(
        layer=layer,
        token=token,
        text=token.form,
        lemma=lemma,
        lemma_norm=normalize(lemma),
        deprel=deprel,
        head=head,
    )
