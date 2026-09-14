"""Exports of a passage or a work: TEI with its phraseological units and reading notes, CoNLL-U
with the corrected analysis and the units.

What is exported is what the user may see in the reading: a draft only for its author, never a
hidden content, never the private notebook. An attestation found automatically is never given as
validated (rule 4). The analysis is the default layer, where validated corrections are written.
Both documents are produced piece by piece, a batch of passages at a time, since a work is long.
"""

import re
from collections import defaultdict
from xml.sax.saxutils import escape, quoteattr

from django.utils import timezone
from django.utils.translation import gettext

from phraseology.models import Attestation, ReadingNote
from phraseology.reading import STATUS_LABELS, ReadingFilters, shown_status, visible_attestations

from .models import Token, TokenAnalysis
from .search import corpus_version, default_layer

BATCH = 200
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
FORMATS = {
    "tei": ("tei.xml", "application/tei+xml; charset=utf-8"),
    "conllu": ("conllu", "text/plain; charset=utf-8"),
}


def export_filename(edition, reference, extension):
    name = edition.work.cts_id + (f"-{reference}" if reference else "")
    return f"{re.sub(r'[^A-Za-z0-9.-]+', '_', name)}.{extension}"


class _Batch:
    """Some passages with their words, the analysis of the words, and what is attested there."""

    def __init__(self, passages, layer, visible):
        self.passages = passages
        pks = [passage.pk for passage in passages]
        self.words = defaultdict(list)
        for token in Token.objects.filter(passage_id__in=pks).order_by("position"):
            self.words[token.passage_id].append(token)
        self.analyses = defaultdict(list)
        if layer is not None:
            analyses = TokenAnalysis.objects.filter(layer=layer, token__passage_id__in=pks)
            for analysis in analyses.order_by("token_id", "part"):
                self.analyses[analysis.token_id].append(analysis)
        rows = list(
            Attestation.tokens.through.objects.filter(
                token__passage_id__in=pks, attestation__in=visible
            )
            .order_by("token__position")
            .values_list("attestation_id", "token_id")
        )
        self.attestations = visible.in_bulk({pk for pk, _token in rows})
        self.attested = defaultdict(list)
        self.attestation_words = defaultdict(list)
        for attestation_id, token_id in rows:
            self.attested[token_id].append(self.attestations[attestation_id])
            self.attestation_words[attestation_id].append(token_id)
        note_rows = list(
            ReadingNote.tokens.through.objects.filter(
                token__passage_id__in=pks, readingnote__is_hidden=False
            )
            .order_by("token__position")
            .values_list("readingnote_id", "token_id")
        )
        self.notes = ReadingNote.objects.select_related("created_by").in_bulk(
            {pk for pk, _token in note_rows}
        )
        self.note_words = defaultdict(list)
        for note_id, token_id in note_rows:
            self.note_words[note_id].append(token_id)


def _batches(user, passages):
    layer = default_layer()
    visible = visible_attestations(user, ReadingFilters(statuses=tuple(STATUS_LABELS)))
    batch = []
    for passage in passages:
        batch.append(passage)
        if len(batch) == BATCH:
            yield _Batch(batch, layer, visible)
            batch = []
    if batch:
        yield _Batch(batch, layer, visible)


# CoNLL-U


def _field(value):
    return "".join(str(value).split()) or "_"


def _misc(items):
    return "|".join(items) or "_"


def _word_line(number, form, analysis, index, misc):
    lemma = upos = feats = deprel = ""
    head = "_"
    if analysis is not None:
        lemma, upos, feats, deprel = analysis.lemma, analysis.upos, analysis.feats, analysis.deprel
        if analysis.head_id is None:
            head = "0" if deprel else "_"
        else:
            found = index.get((analysis.head_id, analysis.head_part))
            head = str(found or 0)
            if not found:
                # The head lies outside the sentence as exported: named by its identifier.
                misc = [*misc, f"HeadTokenId={analysis.head_id}"]
    columns = (number, _field(form), _field(lemma), _field(upos), "_", _field(feats), head)
    return "\t".join(map(str, (*columns, _field(deprel), "_", _misc(misc))))


def _sentence(edition, key, items):
    index, number = {}, 0
    for token, _reference, analyses, _attested in items:
        for analysis in analyses or [None]:
            number += 1
            index[(token.pk, analysis.part if analysis else 0)] = number
    text = "".join(f"{token.before}{token.form}{token.after}" for token, *_rest in items)
    lines = [
        f"# sent_id = {edition.cts_urn}:{key}",
        f"# ref = {items[0][1]}",
        f"# text = {' '.join(text.split())}",
    ]
    number = 0
    for token, reference, analyses, attested in items:
        misc = [f"TokenId={token.pk}", f"Ref={reference}"]
        before, after = _field(token.before), _field(token.after)
        if before != "_":
            misc.append(f"PunctBefore={before}")
        if after != "_":
            misc.append(f"PunctAfter={after}")
        if attested:
            units = ",".join(f"{item.unit_id}:{item.pk}:{shown_status(item)}" for item in attested)
            misc.append(f"Phraseology={units}")
        if len(analyses) > 1:
            span = f"{number + 1}-{number + len(analyses)}"
            lines.append("\t".join([span, _field(token.form), *["_"] * 7, _misc(misc)]))
            for analysis in analyses:
                number += 1
                lines.append(_word_line(number, analysis.text, analysis, index, []))
        else:
            number += 1
            analysis = analyses[0] if analyses else None
            lines.append(_word_line(number, token.form, analysis, index, misc))
    return "\n".join(lines) + "\n\n"


def conllu_export(user, edition, passages):
    """A CoNLL-U document: one sentence per sentence of the analysis (per passage without one).

    MISC gives the stable identifier of each word, its passage, its punctuation and the units it
    attests, as ``unit:attestation:status``.
    """
    layer = default_layer()
    yield f"# newdoc id = {edition.cts_urn}\n"
    yield f"# license = {LICENSE}\n"
    yield f"# corpus_version = {corpus_version().label}\n"
    yield f"# analysis = {layer.label if layer else '_'}\n"
    items, key = [], None
    for batch in _batches(user, passages):
        for passage in batch.passages:
            for token in batch.words[passage.pk]:
                analyses = batch.analyses.get(token.pk, [])
                if analyses:
                    token_key = f"s{analyses[0].sentence}"
                else:
                    token_key = key if layer is not None and key else f"p{passage.pk}"
                if items and token_key != key:
                    yield _sentence(edition, key, items)
                    items = []
                key = token_key
                items.append((token, passage.reference, analyses, batch.attested.get(token.pk, [])))
    if items:
        yield _sentence(edition, key, items)


# TEI


def _attribute(name, value):
    return f" {name}={quoteattr(value)}" if value else ""


def _header(edition, title, url, layer):
    work = edition.work
    description = gettext(
        "Analyse : %(layer)s, avec les corrections validées. Version du corpus : %(corpus)s. "
        "Statut d’une unité : validated (validée par un relecteur), proposed (proposée par une "
        "personne), automatic (repérée automatiquement, jamais vérifiée)."
    ) % {"layer": layer.label if layer else "—", "corpus": corpus_version().label}
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="la">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>{escape(title)}</title>
        <author>{escape(work.author.name)}</author>
      </titleStmt>
      <publicationStmt>
        <publisher>{escape(gettext("Phraséologie latine"))}</publisher>
        <idno type="URI">{escape(url)}</idno>
        <date when="{timezone.now():%Y-%m-%d}"/>
        <availability status="free">
          <licence target="{LICENSE_URL}">{LICENSE}</licence>
        </availability>
      </publicationStmt>
      <sourceDesc>
        <bibl>
          <title>{escape(work.title)}</title>
          <author>{escape(work.author.name)}</author>
          <idno type="CTS-URN">{escape(edition.cts_urn)}</idno>
          <note type="source">{escape(f"{edition.source}, {edition.license}")}</note>
        </bibl>
      </sourceDesc>
    </fileDesc>
    <encodingDesc>
      <p>{escape(description)}</p>
    </encodingDesc>
  </teiHeader>
"""


def _word(token, analyses):
    lemma = "+".join(analysis.lemma for analysis in analyses if analysis.lemma)
    pos = "+".join(analysis.upos for analysis in analyses if analysis.upos)
    msd = "+".join(analysis.feats for analysis in analyses if analysis.feats)
    attributes = _attribute("lemma", lemma) + _attribute("pos", pos) + _attribute("msd", msd)
    return (
        f'{escape(token.before)}<w xml:id="w{token.pk}"{attributes}>{escape(token.form)}</w>'
        f"{escape(token.after)}"
    )


def _target(words):
    return quoteattr(" ".join(f"#w{pk}" for pk in dict.fromkeys(words)))


def tei_export(user, edition, passages, title, url, link):
    """A TEI document: the words with their analysis, the units as spans over the words, the
    reading notes as notes pointing to them. ``link`` makes a site path absolute."""
    yield _header(edition, title, url, default_layer())
    yield "  <text>\n    <body>\n"
    yield f'      <div type="edition" n={quoteattr(edition.cts_urn)}>\n'
    spans, notes = {}, {}
    for batch in _batches(user, passages):
        for passage in batch.passages:
            words = "".join(
                _word(token, batch.analyses.get(token.pk, [])) for token in batch.words[passage.pk]
            )
            yield (
                f'        <ab n={quoteattr(passage.reference)} xml:id="passage-{passage.pk}">'
                f"{words.strip()}</ab>\n"
            )
        for pk, words in batch.attestation_words.items():
            spans.setdefault(pk, (batch.attestations[pk], []))[1].extend(words)
        for pk, words in batch.note_words.items():
            notes.setdefault(pk, (batch.notes[pk], []))[1].extend(words)
    yield "      </div>\n"
    if notes:
        yield '      <div type="notes">\n'
        for note, words in notes.values():
            yield (
                f'        <note type="reading" xml:id="note-{note.pk}" target={_target(words)}>'
                f"<p>{escape(note.text)}</p>"
                f"<bibl><author>{escape(note.created_by.public_name)}</author>"
                f'<date when="{note.created_at:%Y-%m-%d}"/></bibl></note>\n'
            )
        yield "      </div>\n"
    yield "    </body>\n  </text>\n"
    if spans:
        yield '  <standOff>\n    <spanGrp type="phraseology">\n'
        for attestation, words in spans.values():
            unit = attestation.unit
            yield (
                f'      <span xml:id="attestation-{attestation.pk}" '
                f'type="{shown_status(attestation)}" n="{unit.pk}" target={_target(words)} '
                f"corresp={quoteattr(link(unit.get_absolute_url()))}>"
                f"{escape(unit.reference_form)}</span>\n"
            )
        yield "    </spanGrp>\n  </standOff>\n"
    yield "</TEI>\n"
