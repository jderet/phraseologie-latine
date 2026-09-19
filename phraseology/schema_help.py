"""Help to draw a schema: the lemmas of the words written, and the schema checked as it is drawn."""

import re

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext

from corpus.models import TokenAnalysis
from corpus.search import corpus_version, default_layer
from corpus.text import normalize
from corpus.timeouts import TimeLimit

from .composition import components
from .frequency import schema_matches
from .markup import clean_marks, name_key, name_pattern, resolve
from .schema import MAX_RELATIONS, format_schema, parse_schema, schema_lemmas
from .spotting import spot_units, visible_units

# A schema has at most five lemmas; the words of a reference form beyond are not offered.
MAX_WORDS = MAX_RELATIONS + 2
MAX_WORD_LENGTH = 60
MAX_LEMMAS = 5
MAX_SCHEMA_LENGTH = 300
# The count shown while a schema is drawn gives up after this time.
COUNT_SECONDS = 5
# Units offered to be inserted in a drawing.
MAX_UNITS = 10
MAX_QUERY_LENGTH = 100
MAX_FORM_LENGTH = 300
WORD = re.compile(r"[^\W\d_]+")


def written_words(text):
    """The words of a text, without punctuation, as many as a schema may use."""
    return [word[:MAX_WORD_LENGTH] for word in WORD.findall(text or "")][:MAX_WORDS]


def lemma_choices(word, layer=None):
    """The lemmas the analysis gives to a written word, the most frequent first.

    A word the corpus never has but which is a lemma of it is its own lemma; any other word is
    offered as it is, marked unknown.
    """
    layer = layer or default_layer()
    norm = normalize(word)
    lemmas, known = [], False
    if layer is not None:
        with TimeLimit():
            rows = (
                TokenAnalysis.objects.filter(
                    layer=layer, part=0, token__norm=norm, token__edition__is_current=True
                )
                .exclude(lemma_norm="")
                .values("lemma_norm")
                .annotate(total=Count("pk"))
                .order_by("-total", "lemma_norm")
            )
            lemmas = [row["lemma_norm"] for row in rows[: MAX_LEMMAS * 2]]
            # A lemma of a schema is written with letters only.
            lemmas = [lemma for lemma in lemmas if WORD.fullmatch(lemma)][:MAX_LEMMAS]
            known = bool(lemmas) or layer.analyses.filter(lemma_norm=norm).exists()
    if not lemmas:
        lemmas = [norm]
    return {"form": word, "lemmas": lemmas, "known": known}


def _edges_as_json(edges):
    return [
        {
            "head": edge.head,
            "relations": list(edge.relations),
            "dependent": edge.dependent,
            "optional": edge.optional,
        }
        for edge in edges
    ]


def _unit_json(unit, with_edges=True):
    data = {
        "pk": unit.pk,
        "reference_form": unit.reference_form,
        "status": unit.get_status_display(),
        "url": unit.get_absolute_url(),
    }
    if with_edges:
        try:
            data["edges"] = _edges_as_json(parse_schema(unit.schema))
        except ValidationError:
            data["edges"] = []
    return data


def unit_schemas(user, query):
    """Units the user may see whose reference form contains the query, with their schemas.

    The query matches whatever its macrons, u or v, i or j; a unit of that very name comes first.
    """
    query = " ".join((query or "").split())[:MAX_QUERY_LENGTH]
    if not name_key(query):
        return []
    units = (
        visible_units(user)
        .exclude(schema="")
        .filter(reference_form__iregex=name_pattern(query, whole=False))
        .order_by("reference_form", "pk")
    )
    found = []
    for unit in sorted(
        units[:MAX_UNITS], key=lambda unit: name_key(unit.reference_form) != name_key(query)
    ):
        data = _unit_json(unit)
        if data["edges"]:
            found.append(data)
    return found


def form_help(user, text, schema=""):
    """A reference form being written, as the drawing shows it under the field.

    The units its marks name, chosen as on the page of the unit, and the known units found in
    its words that no mark names yet, to suggest.
    """
    result = {"parts": [], "suggestions": [], "errors": []}
    text = " ".join((text or "").split())[:MAX_FORM_LENGTH]
    try:
        text = clean_marks(text)
    except ValidationError as error:
        result["errors"] = error.messages
        return result
    try:
        edges = parse_schema(schema)
    except ValidationError:
        edges = []
    parts = resolve(user, text, edges)
    result["parts"] = [
        {
            "text": part.text,
            "name": part.name,
            "unit": _unit_json(part.unit) if part.unit else None,
            "others": [_unit_json(other, with_edges=False) for other in part.others],
        }
        for part in parts
    ]
    plain, marked = "", []
    for part in parts:
        if part.name:
            marked.append((len(plain), len(plain) + len(part.text)))
        plain += part.text
    named = {name_key(part.name) for part in parts if part.name}
    _words, spots = spot_units(plain, user, describe=False)
    for spot in spots:
        end = spot.start + len(spot.excerpt)
        if (
            not spot.unit.schema
            or name_key(spot.unit.reference_form) in named
            # The unit being written is no suggestion for itself.
            or name_key(spot.excerpt) == name_key(plain)
            or any(spot.start < stop and start < end for start, stop in marked)
        ):
            continue
        suggestion = _unit_json(spot.unit)
        if suggestion["edges"]:
            result["suggestions"].append({**suggestion, "excerpt": spot.excerpt})
    return result


def check_schema(text, slot=False, count=False, user=None):
    """A schema as the drawing needs it: its relations, its written form, or its errors.

    With ``count``, the occurrences in the core of the corpus, if they are counted in time;
    with ``user``, the units this user may see that are part of the schema.
    """
    text = text or ""
    result = {"text": "", "edges": [], "errors": []}
    if len(text) > MAX_SCHEMA_LENGTH:
        result["errors"] = [
            gettext("Un schéma compte au plus %(limit)d caractères.") % {"limit": MAX_SCHEMA_LENGTH}
        ]
        return result
    try:
        edges = parse_schema(text, slot=slot)
    except ValidationError as error:
        result["errors"] = error.messages
        return result
    result["text"] = format_schema(edges)
    result["edges"] = _edges_as_json(edges)
    if user is not None:
        result["components"] = [
            {
                "reference_form": component.unit.reference_form,
                "status": component.unit.get_status_display(),
                "url": component.unit.get_absolute_url(),
                "lemmas": schema_lemmas(component.edges),
            }
            for component in components(user, edges)
        ]
    layer = default_layer()
    if count and edges and layer is not None:
        result["search_url"] = (
            f"{reverse('phraseology:schema_search')}?{urlencode({'schema': result['text']})}"
        )
        with TimeLimit(COUNT_SECONDS) as limit:
            result["core"] = schema_matches(edges, layer, core_only=True).count()
        if limit.exceeded:
            result["core"] = None
            result["exceeded"] = True
        elif result["core"] == 0:
            result["version"] = corpus_version().label
    return result
