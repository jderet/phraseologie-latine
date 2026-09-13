"""Helpers to create translation contents in tests, shared with other applications."""

from translations.models import License, SourceText
from translations.segmentation import Sentence
from translations.services import create_source_text

SENTENCES = ("Il pleut.", "Nous restons à la maison.", "Demain, nous partirons.")


def make_source_text(user, sentences=SENTENCES, **fields):
    fields.setdefault("title", "La pluie")
    fields.setdefault("language", "fr")
    fields.setdefault("license", License.CC_BY_SA_4)
    fields.setdefault("source_url", "https://fr.wikipedia.org/wiki/Pluie")
    parts = [Sentence(text, starts_paragraph=index == 0) for index, text in enumerate(sentences)]
    return create_source_text(SourceText(**fields), user, parts)
