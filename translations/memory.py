"""Translation memory: the Latin already written for a sentence, and for similar sentences.

The public sees the latest public step of published versions; the writers of a version also
see its working text. Nothing is ever inserted without a click (no machine translation, T15).
"""

import difflib
from dataclasses import dataclass, field

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q

from corpus.timeouts import TimeLimit
from moderation.registry import can_view

from .diffs import word_diff
from .models import PersonalMemoryEntry, Segment, TranslatedSegment, TranslationVersion
from .sources import SourceHistory
from .steps import carried, public_step, sentence_at, shown_sentences

# Below this share of common words, a sentence is not similar enough to help.
MIN_SCORE = 60
MAX_MATCHES = 5
MAX_CANDIDATES = 40
MAX_LATIN_PER_MATCH = 3


@dataclass
class Match:
    segment: Segment
    score: int
    chunks: list
    translations: list = field(default_factory=list)


def score(first, second):
    """Share of the words two sentences have in common, in order, from 0 to 100."""
    matcher = difflib.SequenceMatcher(
        None, first.casefold().split(), second.casefold().split(), autojunk=False
    )
    return round(matcher.ratio() * 100)


def other_versions(user, version, segment):
    """The Latin of the same sentence in the other versions of the project the user may see:
    [{version, text}], the main version first."""
    project = version.project
    history = SourceHistory(project.source_text)
    found = []
    queryset = (
        project.versions.visible_to(user)
        .exclude(pk=version.pk)
        .select_related("author")
        .order_by("published_at", "created_at")
    )
    for other in queryset:
        if not can_view(user, other):
            continue
        step, sentences = shown_sentences(user, other)
        if step is not None:
            sentences = history.project(carried(sentences), step.source_state)
        sentence = sentences.get(segment.pk)
        if sentence is not None and sentence.text:
            found.append({"version": other, "text": sentence.text, "step": step})
    found.sort(key=lambda item: not item["version"].is_main)
    return found


def _latin_of(user, candidate):
    """Latin written for a sentence: public steps of published versions, and the working text
    of the versions the user writes."""
    translations = []
    versions = (
        TranslationVersion.objects.filter(project__source_text_id=candidate.source_text_id)
        .filter(
            Q(
                state=TranslationVersion.State.PUBLISHED,
                is_hidden=False,
                project__is_hidden=False,
                project__source_text__is_hidden=False,
            )
            | Q(pk__in=TranslationVersion.objects.written_by(user).values("pk"))
        )
        .select_related("author", "project")
        .distinct()
    )
    own = set(TranslationVersion.objects.written_by(user).values_list("pk", flat=True))
    for version in versions:
        if version.pk in own:
            text = (
                TranslatedSegment.objects.filter(version=version, segment=candidate)
                .values_list("text", flat=True)
                .first()
            )
        else:
            step = public_step(version)
            text = sentence_at(step, candidate.pk) if step else ""
        if text:
            translations.append({"version": version, "text": text})
        if len(translations) >= MAX_LATIN_PER_MATCH:
            break
    return translations


def similar_sentences(user, version, segment):
    """Sentences of any source text that resemble this one and already have Latin, the most
    similar first: [Match]. Empty when the search takes too long."""
    text = segment.text
    with TimeLimit(seconds=3) as limit:
        candidates = list(
            Segment.objects.filter(text__trigram_similar=text)
            .exclude(pk=segment.pk)
            .annotate(similarity=TrigramSimilarity("text", text))
            .order_by("-similarity")[:MAX_CANDIDATES]
        )
    if limit.exceeded:
        return []
    matches, seen = [], set()
    for candidate in candidates:
        if candidate.text in seen:
            continue
        seen.add(candidate.text)
        value = score(candidate.text, text)
        if value < MIN_SCORE:
            continue
        # The old sentences of this very version are its history, not a memory.
        translations = [
            item for item in _latin_of(user, candidate) if item["version"].pk != version.pk
        ]
        if not translations:
            continue
        matches.append(Match(candidate, value, word_diff(candidate.text, text), translations))
    matches.sort(key=lambda match: -match.score)
    return matches[:MAX_MATCHES]


def personal_matches(user, segment):
    """Pairs of the user's own memory whose source resembles the sentence, the most similar
    first: [{entry, score, chunks}]."""
    if not user.is_authenticated:
        return []
    text = segment.text
    with TimeLimit(seconds=3) as limit:
        candidates = list(
            PersonalMemoryEntry.objects.filter(user=user, source__trigram_similar=text)
            .annotate(similarity=TrigramSimilarity("source", text))
            .order_by("-similarity")[:MAX_CANDIDATES]
        )
    if limit.exceeded:
        return []
    found = []
    for entry in candidates:
        value = score(entry.source, text)
        if value >= MIN_SCORE:
            found.append({"entry": entry, "score": value, "chunks": word_diff(entry.source, text)})
    found.sort(key=lambda item: -item["score"])
    return found[:MAX_MATCHES]
