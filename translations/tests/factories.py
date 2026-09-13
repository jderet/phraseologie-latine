"""Helpers to create translation contents in tests, shared with other applications."""

from translations.models import (
    License,
    SourceText,
    Style,
    TranslationProject,
    TranslationVersion,
)
from translations.segmentation import Sentence
from translations.services import (
    create_project,
    create_source_text,
    create_version,
    publish_version,
    save_translation,
)

SENTENCES = ("Il pleut.", "Nous restons à la maison.", "Demain, nous partirons.")
LATIN = ("Pluit.", "Domi manemus.", "Cras proficiscemur.")


def make_source_text(user, sentences=SENTENCES, **fields):
    fields.setdefault("title", "La pluie")
    fields.setdefault("language", "fr")
    fields.setdefault("license", License.CC_BY_SA_4)
    fields.setdefault("source_url", "https://fr.wikipedia.org/wiki/Pluie")
    parts = [Sentence(text, starts_paragraph=index == 0) for index, text in enumerate(sentences)]
    return create_source_text(SourceText(**fields), user, parts)


def make_project(user, source_text=None, **fields):
    source_text = source_text or make_source_text(user)
    fields.setdefault("title", source_text.title)
    return create_project(TranslationProject(source_text=source_text, **fields), user)


def make_version(user, project, style=Style.CICERONIAN, **fields):
    return create_version(TranslationVersion(project=project, style=style, **fields), user)


def translate(version, texts=LATIN):
    segments = version.project.source_text.segments.all()
    for segment, text in zip(segments, texts, strict=False):
        save_translation(version, segment, text, version.author)


def make_published_version(user, project, texts=LATIN, **fields):
    version = make_version(user, project, **fields)
    translate(version, texts)
    publish_version(version, user)
    version.refresh_from_db()
    return version
