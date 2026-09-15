"""Public data as plain dictionaries, shared by the API and the full export (Q65).

Only what an anonymous visitor may see on the site is given: no draft, no hidden content,
no email address (rule 8). People are named by the public name shown beside their
contributions. ``link`` turns a site path into the address to give (absolute in the API).
"""

from django.contrib.auth.models import AnonymousUser
from django.db.models import Prefetch

from corpus.models import AnalysisCorrection, Token
from justifications.models import Evidence, Justification
from moderation.registry import can_view
from phraseology.models import (
    NegativeSearch,
    Neologism,
    ReadingNote,
    Sighting,
    Unit,
    UnitFrequency,
)
from translations.models import TranslationVersion
from translations.steps import public_step, step_sentences

LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
ANONYMOUS = AnonymousUser()


def visible(obj):
    return not obj.is_hidden and can_view(ANONYMOUS, obj)


def _date(value):
    return value.isoformat() if value else None


def _parts(queryset):
    return [part for part in queryset.filter(is_withdrawn=False, is_hidden=False)]


def _words(tokens):
    tokens = sorted(tokens, key=lambda token: token.position)
    if not tokens:
        return None
    passage = tokens[0].passage
    return {
        "urn": passage.urn,
        "citation": passage.citation,
        "edition": passage.edition.cts_urn,
        "word_ids": [token.pk for token in tokens],
        "positions": [token.position for token in tokens],
        "words": [token.form for token in tokens],
    }


def evidence_data(evidence):
    data = {"kind": evidence.kind, "note": evidence.note}
    if evidence.kind == Evidence.Kind.CORPUS:
        data["corpus"] = _words(evidence.tokens.select_related("passage__edition__work__author"))
    elif evidence.work_id:
        data["reference"] = {
            "work": evidence.work.abbreviation,
            "title": evidence.work.title,
            "locator": evidence.locator,
        }
    return data


# Phraseological units


def public_units():
    return (
        Unit.objects.exclude(status=Unit.Status.DRAFT)
        .filter(is_hidden=False)
        .select_related("created_by", "validated_by")
        .order_by("pk")
    )


def unit_summary(unit, link):
    return {
        "id": unit.pk,
        "url": link(unit.get_absolute_url()),
        "reference_form": unit.reference_form,
        "kind": unit.kind,
        "schema": unit.schema,
        "construction": unit.construction,
        "register": unit.register,
        "usage_marks": unit.usage_marks,
        "tags": unit.tags,
        "status": unit.status,
        "created_by": unit.created_by.public_name,
        "created_at": _date(unit.created_at),
        "validated_at": _date(unit.validated_at),
    }


def unit_data(unit, link):
    attestations = (
        unit.attestations.filter(is_withdrawn=False, is_hidden=False)
        .select_related("created_by")
        .prefetch_related("tokens__passage__edition__work__author")
        .order_by("pk")
    )
    frequency = UnitFrequency.objects.filter(unit=unit).first()
    return {
        **unit_summary(unit, link),
        "senses": [
            {
                "id": sense.pk,
                "definition": sense.definition,
                "register": sense.register,
                "usage_note": sense.usage_note,
                "equivalents": [
                    {"language": equivalent.language, "expression": equivalent.expression}
                    for equivalent in _parts(sense.equivalents)
                ],
            }
            for sense in _parts(unit.senses)
        ],
        "realizations": [
            {
                "id": realization.pk,
                "form": realization.form,
                "variation": realization.variation,
                "note": realization.note,
            }
            for realization in _parts(unit.realizations)
        ],
        "relations": [
            {"kind": relation.kind, "target": relation.target_id}
            for relation in _parts(unit.relations.select_related("target"))
            if visible(relation.target)
        ],
        "references": [
            {
                "work": reference.work.abbreviation,
                "locator": reference.locator,
                "note": reference.note,
            }
            for reference in _parts(unit.references.select_related("work"))
        ],
        "attestations": [
            {
                "id": attestation.pk,
                "status": attestation.status,
                # An automatic attestation is never given as validated (rule 4).
                "level": attestation.level,
                "origin": attestation.origin,
                "is_example": attestation.is_example,
                "is_contested": attestation.is_contested,
                "created_by": attestation.created_by.public_name,
                "sense": attestation.sense_id,
                "realization": attestation.realization_id,
                **(_words(attestation.tokens.all()) or {}),
            }
            for attestation in attestations
        ],
        "frequency": (
            {
                "schema": frequency.schema,
                "total": frequency.total,
                "core_total": frequency.core_total,
                "corpus_version": frequency.corpus_version,
                "computed_at": _date(frequency.computed_at),
            }
            if frequency is not None
            else None
        ),
    }


# Neologisms


def public_neologisms():
    return Neologism.objects.filter(is_hidden=False).select_related("created_by").order_by("pk")


def neologism_summary(neologism, link):
    return {
        "id": neologism.pk,
        "url": link(neologism.get_absolute_url()),
        "form": neologism.form,
        "meaning": neologism.meaning,
        "formation": neologism.formation,
        "status": neologism.status,
        "created_by": neologism.created_by.public_name,
        "created_at": _date(neologism.created_at),
    }


def neologism_data(neologism, link):
    return {
        **neologism_summary(neologism, link),
        "justification": neologism.justification,
        "lrl_reference": neologism.lrl_reference,
        "equivalents": [
            {"language": equivalent.language, "expression": equivalent.expression}
            for equivalent in _parts(neologism.equivalents)
        ],
        "evidences": [
            evidence_data(evidence)
            for evidence in neologism.evidences.filter(is_withdrawn=False, is_hidden=False)
        ],
    }


# Published translations


def public_versions():
    return (
        TranslationVersion.objects.filter(
            state=TranslationVersion.State.PUBLISHED,
            is_hidden=False,
            project__is_hidden=False,
            project__source_text__is_hidden=False,
        )
        .select_related("project__source_text", "author")
        .order_by("pk")
    )


def version_summary(version, link):
    source = version.project.source_text
    return {
        "id": version.pk,
        "url": link(version.get_absolute_url()),
        "project": {"id": version.project_id, "title": version.project.title},
        "source_text": {
            "title": source.title,
            "author": source.author,
            "language": source.language,
            "license": source.get_license_display(),
            "url": source.source_url,
        },
        "author": version.author.public_name,
        "style": version.style,
        "style_note": version.style_note,
        "published_at": _date(version.published_at),
        "license": LICENSE,
    }


def step_data(step, link):
    return {
        "number": step.number,
        "message": step.message,
        "created_at": _date(step.created_at),
        "url": link(step.get_absolute_url()),
    }


def version_data(version, link):
    """A published version as the public sees it: the text of its latest public step."""
    step = public_step(version)
    sentences = step_sentences(step) if step else {}
    justifications = (
        Justification.objects.filter(translated_segment__version=version, is_hidden=False)
        .select_related("translated_segment__segment")
        .prefetch_related("units")
        .order_by("translated_segment__segment__order", "pk")
    )
    return {
        **version_summary(version, link),
        "step": step_data(step, link) if step else None,
        "segments": [
            {
                "order": segment.order,
                "source": segment.text,
                "latin": sentences[segment.pk].text if segment.pk in sentences else "",
            }
            for segment in version.project.source_text.segments.order_by("order")
        ],
        "justifications": [
            {
                "segment": justification.translated_segment.segment.order,
                "latin_excerpt": justification.latin_excerpt,
                "strength": justification.strength,
                "comment": justification.comment,
                "corpus_version": justification.corpus_version,
                "units": [unit.pk for unit in justification.units.all() if visible(unit)],
                "evidences": [
                    evidence_data(evidence)
                    for evidence in justification.evidences.filter(
                        is_withdrawn=False, is_hidden=False
                    ).select_related("work")
                ],
            }
            for justification in justifications
        ],
    }


# Searches that found nothing


def public_negative_searches():
    return (
        NegativeSearch.objects.filter(is_hidden=False).select_related("created_by").order_by("pk")
    )


def negative_search_data(search, link):
    return {
        "id": search.pk,
        "url": link(search.get_absolute_url()),
        "expression": search.expression,
        "query": search.query,
        "search_url": link(search.search_url),
        "corpus_version": search.corpus_version,
        "note": search.note,
        "created_by": search.created_by.public_name,
        "created_at": _date(search.created_at),
    }


# Annotations of the texts: sightings, reading notes, validated corrections of the analysis.
# The private notebook is never given.


def _with_words():
    words = Token.objects.select_related("passage__edition__work__author")
    return Prefetch("tokens", queryset=words)


def public_sightings():
    return (
        Sighting.objects.filter(is_hidden=False)
        .select_related("created_by", "attestation__unit")
        .prefetch_related(_with_words())
        .order_by("pk")
    )


def sighting_data(sighting, link):
    attestation = sighting.attestation
    attached = attestation is not None and not attestation.is_withdrawn and visible(attestation)
    return {
        "id": sighting.pk,
        "status": sighting.status,
        "note": sighting.note,
        "attestation": attestation.pk if attached else None,
        "unit": attestation.unit_id if attached else None,
        "created_by": sighting.created_by.public_name,
        "created_at": _date(sighting.created_at),
        **(_words(sighting.tokens.all()) or {}),
    }


def public_reading_notes():
    return (
        ReadingNote.objects.filter(is_hidden=False)
        .select_related("created_by", "passage__edition__work")
        .prefetch_related(_with_words())
        .order_by("pk")
    )


def reading_note_data(note, link):
    return {
        "id": note.pk,
        "url": link(note.get_absolute_url()),
        "text": note.text,
        "created_by": note.created_by.public_name,
        "created_at": _date(note.created_at),
        **(_words(note.tokens.all()) or {}),
    }


def validated_corrections():
    return (
        AnalysisCorrection.objects.filter(
            status=AnalysisCorrection.Status.VALIDATED, is_hidden=False
        )
        .select_related("created_by", "token__passage__edition__work__author")
        .order_by("pk")
    )


def correction_data(correction, link):
    return {
        "id": correction.pk,
        "word_id": correction.token_id,
        "part": correction.part,
        "lemma": correction.lemma,
        "upos": correction.upos,
        "feats": correction.feats,
        "head": correction.head_id,
        "deprel": correction.deprel,
        "reason": correction.reason,
        "created_by": correction.created_by.public_name,
        "created_at": _date(correction.created_at),
        "validated_at": _date(correction.reviewed_at),
        **(_words([correction.token]) or {}),
    }
