"""A small corpus to cite in tests, without importing Perseus files."""

from corpus.models import Author, Edition, Passage, Token, Work
from corpus.text import normalize


def make_passage(words, reference="1.1"):
    author, _created = Author.objects.get_or_create(
        cts_id="phi0474",
        defaults={
            "name_fr": "Cicéron",
            "name_en": "Cicero",
            "latin_name": "M. Tullius Cicero",
            "abbreviation": "Cic.",
        },
    )
    work, _created = Work.objects.get_or_create(
        cts_urn="urn:cts:latinLit:phi0474.phi055",
        defaults={
            "author": author,
            "title": "De officiis",
            "abbreviation": "Off.",
            "is_core": True,
        },
    )
    edition, _created = Edition.objects.get_or_create(
        work=work,
        is_current=True,
        defaults={
            "cts_urn": "urn:cts:latinLit:phi0474.phi055.perseus-lat1",
            "source": "Perseus",
            "source_path": "data/phi0474/phi055/phi0474.phi055.perseus-lat1.xml",
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
