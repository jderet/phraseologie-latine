"""Loading the catalogue and parsed Perseus editions into the database."""

from collections import Counter
from dataclasses import asdict

from django.db import transaction
from django.utils.translation import gettext as _

from .models import Author, Edition, Passage, Token, Work
from .text import normalize

SOURCE_NAME = "Perseus canonical-latinLit"
LICENSE = "CC BY-SA 4.0"
TOKEN_BATCH_SIZE = 5000


class ImportFailed(ValueError):
    pass


def sync_author(entry):
    """Create or update an author from its catalogue entry."""
    defaults = asdict(entry)
    cts_id = defaults.pop("cts_id")
    author, _created = Author.objects.update_or_create(cts_id=cts_id, defaults=defaults)
    return author


def sync_work(entry, author):
    """Create or update a work from its catalogue entry."""
    defaults = {
        key: value
        for key, value in asdict(entry).items()
        if key not in {"cts_urn", "author", "edition_file", "exclude"}
    }
    work, _created = Work.objects.update_or_create(
        cts_urn=entry.cts_urn, defaults={**defaults, "author": author}
    )
    return work


def _check(work, parsed):
    if not parsed.urn.startswith(f"{work.cts_urn}."):
        raise ImportFailed(
            _("l’édition %(edition)s n’appartient pas à l’œuvre %(work)s")
            % {"edition": parsed.urn, "work": work.cts_urn}
        )
    if not parsed.passages:
        raise ImportFailed(_("aucun passage trouvé"))
    references = Counter(passage.reference for passage in parsed.passages)
    problems = sorted(ref or "(vide)" for ref, count in references.items() if count > 1 or not ref)
    if problems:
        raise ImportFailed(
            _("références en double ou vides : %(references)s")
            % {"references": ", ".join(problems[:20])}
        )


@transaction.atomic
def import_edition(work, parsed, source_path, source_version):
    """Store a parsed edition and make it current; return (edition, created).

    An edition already imported for this version of the source is left untouched.
    """
    existing = Edition.objects.filter(cts_urn=parsed.urn, source_version=source_version).first()
    if existing is not None:
        return existing, False
    _check(work, parsed)
    Edition.objects.filter(work=work, is_current=True).update(is_current=False)
    edition = Edition.objects.create(
        work=work,
        cts_urn=parsed.urn,
        source=SOURCE_NAME,
        source_path=source_path,
        source_version=source_version,
        license=LICENSE,
        citation_scheme=parsed.citation_scheme,
        passage_count=len(parsed.passages),
        token_count=parsed.token_count,
    )
    passages = Passage.objects.bulk_create(
        [
            Passage(
                edition=edition,
                order=order,
                reference=item.reference,
                heading=item.heading[:300],
                speaker=item.speaker[:100],
                text=item.text,
            )
            for order, item in enumerate(parsed.passages)
        ],
        batch_size=1000,
    )
    batch = []
    position = 0
    for passage, item in zip(passages, parsed.passages, strict=True):
        for token in item.tokens:
            batch.append(
                Token(
                    edition=edition,
                    passage=passage,
                    position=position,
                    form=token.form,
                    norm=normalize(token.form),
                    before=token.before,
                    after=token.after,
                    is_foreign=token.is_foreign,
                )
            )
            position += 1
            if len(batch) >= TOKEN_BATCH_SIZE:
                Token.objects.bulk_create(batch)
                batch = []
    Token.objects.bulk_create(batch)
    return edition, True
