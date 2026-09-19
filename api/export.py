"""The full export of the public data: one zip archive of JSON files (Q65).

It holds what the API gives, all at once, with a notice of the licence. Drafts, hidden
content and email addresses are never in it (rule 8).
"""

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from corpus.search import corpus_version

from . import serializers

PREFIX = "phraseologie-latine-"

NOTICE = """Phraséologie latine : export complet des données publiques
==========================================================

Date : {date}
Version du corpus : {corpus}

Contenu
- fiches.json : fiches phraséologiques proposées, validées ou contestées ({units})
- neologismes.json : lexique des néologismes ({neologisms})
- mots-abstraits.json : mots abstraits, classes de mots nommées {{liquide}} dans les
  schémas ({abstract_words})
- versions.json : versions de traduction publiées, avec leurs justifications ({versions})
- recherches-infructueuses.json : recherches qui n'ont rien trouvé ({searches})
- reperages.json : repérages de phraséologie sans fiche, rattachés ou non ({sightings})
- notes-de-lecture.json : notes de lecture publiques sur des mots du corpus ({notes})
- corrections.json : corrections validées de l'analyse automatique ({corrections})
- sujets.json : sujets ouverts sur les projets de traduction ({topics})
- glossaires.json : termes adoptés des glossaires des projets ({glossary})

Les attestations sont dans fiches.json. Les mots sont désignés par leur identifiant stable.

Licence : CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).
Créditer « contributeurs de Phraséologie latine » ; chaque élément donne le nom public de
son auteur. Les citations du corpus viennent de Perseus canonical-latinLit (CC BY-SA 4.0).
Les brouillons et les contenus masqués ne sont pas exportés, ni aucune adresse e-mail,
ni le carnet personnel des lecteurs, ni leur mémoire personnelle, leurs notifications ou les
commentaires des brouillons.
Une attestation de niveau « automatic » a été repérée automatiquement, jamais vérifiée.
"""


@dataclass(frozen=True)
class Export:
    path: Path
    created_at: datetime
    size: int


def _link(path):
    return path


def write_export(directory=None, now=None):
    """Write the archive in ``directory``; return its path and the number of items per file."""
    directory = Path(directory or settings.EXPORT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    now = now or timezone.now()
    datasets = {
        "fiches.json": [serializers.unit_data(u, _link) for u in serializers.public_units()],
        "neologismes.json": [
            serializers.neologism_data(n, _link) for n in serializers.public_neologisms()
        ],
        "mots-abstraits.json": [
            serializers.abstract_word_data(w, _link) for w in serializers.public_abstract_words()
        ],
        "versions.json": [
            serializers.version_data(v, _link) for v in serializers.public_versions()
        ],
        "recherches-infructueuses.json": [
            serializers.negative_search_data(s, _link)
            for s in serializers.public_negative_searches()
        ],
        "reperages.json": [
            serializers.sighting_data(s, _link) for s in serializers.public_sightings()
        ],
        "notes-de-lecture.json": [
            serializers.reading_note_data(n, _link) for n in serializers.public_reading_notes()
        ],
        "corrections.json": [
            serializers.correction_data(c, _link) for c in serializers.validated_corrections()
        ],
        "sujets.json": [serializers.topic_data(t, _link) for t in serializers.public_topics()],
        "glossaires.json": [
            serializers.glossary_entry_data(e, _link) for e in serializers.public_glossary()
        ],
    }
    counts = {name: len(items) for name, items in datasets.items()}
    notice = NOTICE.format(
        date=now.date().isoformat(),
        corpus=corpus_version().label,
        units=counts["fiches.json"],
        neologisms=counts["neologismes.json"],
        abstract_words=counts["mots-abstraits.json"],
        versions=counts["versions.json"],
        searches=counts["recherches-infructueuses.json"],
        sightings=counts["reperages.json"],
        notes=counts["notes-de-lecture.json"],
        corrections=counts["corrections.json"],
        topics=counts["sujets.json"],
        glossary=counts["glossaires.json"],
    )
    path = directory / f"{PREFIX}{now:%Y-%m-%d-%H%M%S}.zip"
    partial = path.with_suffix(".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("LISEZMOI.txt", notice)
        for name, items in datasets.items():
            archive.writestr(
                name, json.dumps(items, ensure_ascii=False, indent=1, cls=DjangoJSONEncoder)
            )
    partial.replace(path)
    return path, counts


def latest_export(directory=None):
    """The most recent archive, or None."""
    directory = Path(directory or settings.EXPORT_DIR)
    archives = sorted(directory.glob(f"{PREFIX}*.zip")) if directory.is_dir() else []
    if not archives:
        return None
    path = archives[-1]
    stat = path.stat()
    return Export(
        path,
        datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
        stat.st_size,
    )
