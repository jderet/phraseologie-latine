"""Automatic linguistic analysis of the corpus, stored in versioned layers.

The analyser reads the text of whole passages. Its tokens are aligned back to the words
of the edition by character offsets, so every analysis points to a stable word (rule 1)
whatever the analyser's own tokenization: an enclitic split off a word (senatus + que)
becomes a second part of the same word, punctuation is left aside.
"""

import difflib
from dataclasses import dataclass, field

from django.db import transaction

from .models import Token, TokenAnalysis
from .text import normalize

CHUNK_CHARACTERS = 20_000
ROW_BATCH_SIZE = 5_000


@dataclass(frozen=True)
class AnalyzedToken:
    """A token as returned by an analyser, positioned in the text it received."""

    start: int
    text: str
    lemma: str = ""
    upos: str = ""
    feats: str = ""
    deprel: str = ""
    # Index of the head token in the same text; None for the root of a sentence.
    head: int | None = None
    sentence: int = 0


@dataclass
class Chunk:
    text: str
    # (token id, start, end) of the edition words, in order.
    words: list[tuple[int, int, int]] = field(default_factory=list)


def build_chunks(tokens, max_characters=CHUNK_CHARACTERS):
    """Texts of limited size made of whole passages, with the position of every word.

    ``tokens`` are the words of an edition in order, with id, passage_id, before, form, after.
    """
    parts, words, length, passage = [], [], 0, None
    for token in tokens:
        if token.passage_id != passage:
            if length >= max_characters:
                yield Chunk("".join(parts), words)
                parts, words, length = [], [], 0
            if length:
                parts.append("\n")
                length += 1
            passage = token.passage_id
        start = length + len(token.before)
        piece = token.before + token.form + token.after
        parts.append(piece)
        length += len(piece)
        words.append((token.id, start, start + len(token.form)))
    if words:
        yield Chunk("".join(parts), words)


def offset_map(original, produced):
    """Positions in ``produced`` mapped back to positions in ``original``, or None if equal.

    LatinCy rewrites some characters while tokenizing (v is written u). When the length of
    the text does not change, positions are unchanged; otherwise they are realigned on the
    blocks the two texts have in common.
    """
    if len(original) == len(produced):
        return None
    mapping = [0] * (len(produced) + 1)
    matcher = difflib.SequenceMatcher(None, original, produced, autojunk=False)
    for _tag, start, end, produced_start, produced_end in matcher.get_opcodes():
        for offset in range(produced_end - produced_start):
            mapping[produced_start + offset] = start + min(offset, max(end - start - 1, 0))
    mapping[len(produced)] = len(original)
    return mapping


def align(chunk, analyzed):
    """Map each analysed token starting inside a word to (token id, part number)."""
    places = {}
    parts = {}
    word = 0
    for index, item in enumerate(analyzed):
        while word < len(chunk.words) and chunk.words[word][2] <= item.start:
            word += 1
        if word == len(chunk.words):
            break
        token_id, start, _end = chunk.words[word]
        if item.start >= start:
            part = parts.get(token_id, 0)
            parts[token_id] = part + 1
            places[index] = (token_id, part)
    return places


def analysis_rows(layer, chunk, analyzed, first_sentence=0):
    """Rows to store for one analysed chunk, and the number of the next sentence."""
    places = align(chunk, analyzed)
    rows = []
    for index, (token_id, part) in places.items():
        item = analyzed[index]
        head = places.get(item.head) if item.head is not None else None
        rows.append(
            TokenAnalysis(
                layer=layer,
                token_id=token_id,
                part=part,
                text=item.text[:200],
                lemma=item.lemma[:200],
                lemma_norm=normalize(item.lemma)[:200],
                upos=item.upos[:10],
                feats=item.feats[:300],
                deprel=item.deprel[:30],
                head_id=head[0] if head else None,
                head_part=head[1] if head else 0,
                sentence=first_sentence + item.sentence,
            )
        )
    last_sentence = max((item.sentence for item in analyzed), default=-1)
    return rows, first_sentence + last_sentence + 1


@transaction.atomic
def analyze_edition(edition, layer, analyzer):
    """Analyse every word of an edition into ``layer``; return the number of rows stored."""
    tokens = (
        Token.objects.filter(edition=edition)
        .order_by("position")
        .only("id", "passage_id", "before", "form", "after")
    )
    chunks = list(build_chunks(tokens.iterator(chunk_size=10_000)))
    sentence = 0
    batch = []
    stored = 0
    results = analyzer.analyze([chunk.text for chunk in chunks])
    for chunk, analyzed in zip(chunks, results, strict=True):
        rows, sentence = analysis_rows(layer, chunk, analyzed, sentence)
        batch.extend(rows)
        if len(batch) >= ROW_BATCH_SIZE:
            TokenAnalysis.objects.bulk_create(batch)
            stored += len(batch)
            batch = []
    TokenAnalysis.objects.bulk_create(batch)
    stored += len(batch)
    layer.editions.add(edition)
    return stored


class SpacyAnalyzer:
    """LatinCy through spaCy, installed on the Mac only (requirements-corpus.txt)."""

    def __init__(self, model="la_core_web_lg"):
        import spacy  # not installed on the server nor in continuous integration

        self.nlp = spacy.load(model, exclude=["ner"])
        self.nlp.max_length = CHUNK_CHARACTERS * 20
        self.tool = f"LatinCy {model}"
        self.tool_version = self.nlp.meta.get("version", "")
        self.details = {"spacy": spacy.__version__, "pipeline": self.nlp.pipe_names}

    def analyze(self, texts):
        # One process: spaCy's multiprocessing hangs with this model on macOS.
        docs = self.nlp.pipe(texts, batch_size=4)
        for text, doc in zip(texts, docs, strict=True):
            mapping = offset_map(text, doc.text)
            sentences = {}
            for number, sentence in enumerate(doc.sents):
                for token in sentence:
                    sentences[token.i] = number
            yield [
                AnalyzedToken(
                    start=token.idx if mapping is None else mapping[token.idx],
                    text=token.text,
                    lemma=token.lemma_,
                    upos=token.pos_,
                    feats=str(token.morph),
                    deprel=token.dep_,
                    head=None if token.head.i == token.i else token.head.i,
                    sentence=sentences.get(token.i, 0),
                )
                for token in doc
            ]
