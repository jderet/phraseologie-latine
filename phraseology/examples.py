"""Example units, to see phraseology in the texts on a development machine.

``create_example`` builds a realistic unit, focused on Cicero's De officiis 1, whose
attestations have every status an attestation can have; ``delete_examples`` removes the
examples and whatever other accounts added to them. The units are created by a dedicated
account, which is how they are found again. The commands refuse to run outside development.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef, ProtectedError, Q
from django.utils.translation import gettext

from accounts.models import User
from accounts.roles import CONTRIBUTOR, REVIEWER
from corpus.models import Token, Work
from justifications.models import BibliographicWork, Evidence, Justification
from justifications.services import corpus_evidence
from moderation.models import Comment, Report, Revision, Vote

from .frequency import occurrence_words, schema_matches
from .models import (
    AbstractWord,
    Attestation,
    Candidate,
    Equivalent,
    Kind,
    Realization,
    Sense,
    Unit,
    UnitReference,
    UnitRelation,
    UsageMark,
)
from .schema import parse_schema
from .services import (
    add_attestations,
    create_abstract_word,
    create_unit,
    propose_unit,
    record_automatic_attestations,
    refresh_frequency,
    review_attestations,
    save_part,
    set_example,
    validate_abstract_word,
    validate_unit,
)

EXAMPLE_AUTHOR = "exemples@exemples.invalid"
EXAMPLE_REVIEWER = "relecture@exemples.invalid"
FOCUS_WORK = "urn:cts:latinLit:phi0474.phi055"
FOCUS_BOOK = "1."
# Occurrences taken elsewhere: the first of each author, up to this many authors.
OTHER_AUTHORS = 3
OUTSIDE_AUTHORS = 3

VALIDATED, PROPOSED, DRAFT = Unit.Status.VALIDATED, Unit.Status.PROPOSED, Unit.Status.DRAFT
ELEVATED, STANDARD = Work.Register.ELEVATED, Work.Register.STANDARD
BASE, PASSIVE = Realization.Variation.BASE, Realization.Variation.PASSIVE
INSERTION = Realization.Variation.INSERTION
WORD_ORDER, OTHER = Realization.Variation.WORD_ORDER, Realization.Variation.OTHER


@dataclass(frozen=True)
class Example:
    """An example unit: a schema, or for a unit without schema, consecutive normalized words."""

    reference_form: str
    kind: str
    definition: str
    equivalents: tuple = ()  # (language, expression)
    schema: str = ""
    words: tuple = ()
    construction: str = ""
    register: str = STANDARD
    usage_marks: tuple = ()
    realizations: tuple = ()  # (form, variation)
    reference: tuple | None = None  # (abbreviation of a bibliographic work, locator)
    status: str = VALIDATED


# Abstract words the examples use: (name, label, definition, rules). One that already exists,
# whoever made it, is used as it is.
EXAMPLE_ABSTRACTS = (
    (
        "liquide",
        "nom désignant un liquide",
        "Liquides que l’on boit ou que l’on verse : eau, vin, lait, boisson.",
        [{"upos": [], "feats": [], "lemmas": ["aqua", "uinum", "merum", "lac", "potio"]}],
    ),
    (
        "possesseur",
        "nom ou pronom au génitif, ou adjectif possessif",
        "Celui à qui l’on rapporte une chose : Caesaris, eius, meā, uestrā. L’analyse rattache "
        "le génitif par nmod, l’adjectif possessif par det.",
        [
            {"upos": ["NOUN", "PROPN", "PRON"], "feats": ["Case=Gen"], "lemmas": []},
            {"upos": [], "feats": [], "lemmas": ["meus", "tuus", "suus", "noster", "uester"]},
        ],
    ),
)

EXAMPLES = (
    Example(
        "bellum gerere",
        Kind.VERB_NOUN,
        "faire la guerre, conduire une guerre",
        (("fr", "faire la guerre"), ("en", "to wage war")),
        schema="gero -obj|nsubj:pass-> bellum; gero -(sp)-> cum; cum -reg-> aliquis",
        construction="bellum gerere cum aliquo, contra ou adversus aliquem",
        realizations=(
            ("bellum gerere", BASE),
            ("bellum geritur", PASSIVE),
            ("bellum cum aliquo gerere", INSERTION),
        ),
        reference=("Gaffiot", "s. v. gero"),
    ),
    Example(
        "rem gerere",
        Kind.VERB_NOUN,
        "mener une affaire ; en contexte militaire, conduire les opérations",
        (("fr", "conduire les opérations"), ("en", "to conduct operations")),
        schema="gero -obj|nsubj:pass-> res",
        construction="rem gerere ; rem bene ou male gerere",
        reference=("L&S", "s. v. gero"),
    ),
    Example(
        "rem publicam gerere",
        Kind.VERB_NOUN,
        "prendre part aux affaires publiques, exercer des charges politiques",
        (("fr", "prendre part aux affaires publiques"), ("en", "to take part in public affairs")),
        schema="gero -obj|nsubj:pass-> res; res -amod-> publicus",
        construction="rem publicam gerere",
        register=ELEVATED,
        reference=("Gaffiot", "s. v. gero"),
        status=PROPOSED,
    ),
    Example(
        "res publica",
        Kind.ADJECTIVE_NOUN,
        "l’État, la chose publique ; les affaires publiques",
        (("fr", "l’État"), ("en", "the State")),
        schema="res -amod-> publicus",
        construction="res publica ; de re publica ; rei publicae causa",
        realizations=(("res publica", BASE), ("publicae res", WORD_ORDER)),
        reference=("Gaffiot", "s. v. publicus"),
    ),
    Example(
        "operam dare",
        Kind.VERB_NOUN,
        "s’appliquer à quelque chose, y consacrer ses soins",
        (("fr", "s’appliquer à"), ("en", "to devote oneself to")),
        schema="do -obj|nsubj:pass-> opera",
        construction="operam dare alicui rei ; operam dare ut, ne + subjonctif",
        realizations=(("operam dare", BASE), ("dare operam", WORD_ORDER)),
        reference=("L&S", "s. v. opera"),
    ),
    Example(
        "rationem habere",
        Kind.VERB_NOUN,
        "tenir compte de quelque chose, y avoir égard",
        (("fr", "tenir compte de"), ("en", "to take into account")),
        schema="habeo -obj|nsubj:pass-> ratio",
        construction="rationem habere alicuius rei",
        reference=("Gaffiot", "s. v. ratio"),
    ),
    Example(
        "iniuriam propulsare",
        Kind.VERB_NOUN,
        "repousser une injustice, pour soi ou pour les siens",
        (("fr", "repousser une injustice"), ("en", "to ward off a wrong")),
        schema="propulso -obj|nsubj:pass-> iniuria",
        construction="iniuriam propulsare ab aliquo",
        register=ELEVATED,
        reference=("Gaffiot", "s. v. propulso"),
        status=PROPOSED,
    ),
    Example(
        "mortem oppetere",
        Kind.VERB_NOUN,
        "aller au-devant de la mort, mourir, souvent pour une cause",
        (("fr", "affronter la mort"), ("en", "to meet one’s death")),
        schema="oppeto -obj|nsubj:pass-> mors",
        construction="mortem oppetere pro aliquo, pro patria",
        register=ELEVATED,
        reference=("Gaffiot", "s. v. oppeto"),
    ),
    Example(
        "arma ferre",
        Kind.VERB_NOUN,
        "porter les armes, combattre",
        (("fr", "porter les armes"), ("en", "to bear arms")),
        schema="fero -obj|nsubj:pass-> arma",
        construction="arma ferre contra, adversus aliquem",
        reference=("L&S", "s. v. arma"),
        status=DRAFT,
    ),
    Example(
        "populus Romanus",
        Kind.ADJECTIVE_NOUN,
        "le peuple romain, comme corps politique",
        (("fr", "le peuple romain"), ("en", "the Roman people")),
        schema="populus -amod-> romanus",
        construction="populus Romanus ; senatus populusque Romanus",
        register=ELEVATED,
        reference=("L&S", "s. v. populus"),
    ),
    Example(
        "vir bonus",
        Kind.ADJECTIVE_NOUN,
        "l’homme de bien, l’homme honnête : notion morale",
        (("fr", "homme de bien"), ("en", "good man")),
        schema="vir -amod-> bonus",
        construction="vir bonus ; vir bonus et sapiens",
        reference=("Gaffiot", "s. v. bonus"),
    ),
    Example(
        "ius civile",
        Kind.ADJECTIVE_NOUN,
        "le droit civil, propre aux citoyens romains",
        (("fr", "droit civil"), ("en", "civil law")),
        schema="ius -amod-> civilis",
        construction="ius civile ; de iure civili",
        reference=("L&S", "s. v. civilis"),
    ),
    Example(
        "summum bonum",
        Kind.ADJECTIVE_NOUN,
        "le souverain bien, fin dernière de l’action en philosophie",
        (("fr", "souverain bien"), ("en", "supreme good")),
        schema="bonum -amod-> summus",
        construction="summum bonum ; de summo bono",
        register=ELEVATED,
        reference=("Gaffiot", "s. v. bonum"),
    ),
    Example(
        "genus humanum",
        Kind.ADJECTIVE_NOUN,
        "le genre humain",
        (("fr", "genre humain"), ("en", "mankind")),
        schema="genus -amod-> humanus",
        construction="genus humanum ; generis humani societas",
        register=ELEVATED,
        reference=("Gaffiot", "s. v. genus"),
        status=PROPOSED,
    ),
    Example(
        "res familiaris",
        Kind.ADJECTIVE_NOUN,
        "le patrimoine, les biens de la famille",
        (("fr", "patrimoine"), ("en", "family property")),
        schema="res -amod-> familiaris",
        construction="rem familiarem augere, tueri, amittere",
        reference=("Gaffiot", "s. v. familiaris"),
    ),
    Example(
        "communis utilitas",
        Kind.ADJECTIVE_NOUN,
        "l’intérêt commun, l’utilité de tous",
        (("fr", "intérêt commun"), ("en", "common good")),
        schema="utilitas -amod-> communis",
        construction="communis utilitas ; communes utilitates",
        register=ELEVATED,
        reference=("L&S", "s. v. utilitas"),
        status=PROPOSED,
    ),
    Example(
        "magnitudo animi",
        Kind.NOUN_NOUN,
        "la grandeur d’âme, l’une des quatre sources de l’honnête dans le De officiis",
        (("fr", "grandeur d’âme"), ("en", "greatness of soul")),
        schema="magnitudo -nmod-> animus",
        construction="magnitudo animi ; animi magnitudo",
        register=ELEVATED,
        realizations=(("magnitudo animi", BASE), ("animi magnitudo", WORD_ORDER)),
        reference=("Gaffiot", "s. v. magnitudo"),
    ),
    Example(
        "motus animi",
        Kind.NOUN_NOUN,
        "mouvement de l’âme, émotion",
        (("fr", "émotion"), ("en", "emotion")),
        schema="motus -nmod-> animus",
        construction="motus animi ; animi motus",
        register=ELEVATED,
        reference=("Gaffiot", "s. v. motus"),
        status=PROPOSED,
    ),
    Example(
        "perturbatio animi",
        Kind.NOUN_NOUN,
        "trouble de l’âme, passion : terme de la philosophie stoïcienne",
        (("fr", "passion"), ("en", "passion")),
        schema="perturbatio -nmod-> animus",
        construction="perturbatio animi ; animi perturbationes",
        register=ELEVATED,
        reference=("L&S", "s. v. perturbatio"),
    ),
    Example(
        "cupiditas gloriae",
        Kind.NOUN_NOUN,
        "le désir de gloire",
        (("fr", "soif de gloire"), ("en", "desire for glory")),
        schema="cupiditas -nmod-> gloria",
        construction="cupiditas gloriae ; gloriae cupiditas",
        reference=("Gaffiot", "s. v. cupiditas"),
        status=PROPOSED,
    ),
    Example(
        "late patere",
        Kind.ADVERB_VERB,
        "s’étendre au loin ; au figuré, avoir une large portée",
        (("fr", "s’étendre largement"), ("en", "to extend widely")),
        schema="pateo -advmod-> late",
        construction="late, latius, latissime patere",
        realizations=(("late patere", BASE), ("latissime patet", OTHER)),
        reference=("Gaffiot", "s. v. pateo"),
    ),
    Example(
        "ut supra dixi",
        Kind.FORMULA,
        "formule de renvoi à ce qui a déjà été dit",
        (("fr", "comme je l’ai dit plus haut"), ("en", "as I said above")),
        schema="dico -advmod-> supra",
        construction="ut supra dixi ; quae supra dicta sunt",
        reference=("L&S", "s. v. supra"),
        status=PROPOSED,
    ),
    Example(
        "quam ob rem",
        Kind.DISCOURSE,
        "c’est pourquoi : connecteur de conséquence",
        (("fr", "c’est pourquoi"), ("en", "therefore")),
        words=("quam", "ob", "rem"),
        construction="en tête de phrase ou de proposition",
        reference=("Gaffiot", "s. v. quamobrem"),
        status=PROPOSED,
    ),
    Example(
        "esse videatur",
        Kind.CLAUSULA,
        "fin de période rythmée, jugée caractéristique de Cicéron dès l’Antiquité "
        "(Quint. Inst. 10, 2, 18)",
        words=("esse", "uideatur"),
        register=ELEVATED,
        status=PROPOSED,
    ),
    Example(
        "iter carpere",
        Kind.VERB_NOUN,
        "faire route, cheminer",
        (("fr", "faire route"), ("en", "to make one’s way")),
        schema="carpo -obj|nsubj:pass-> iter",
        construction="iter, viam carpere",
        register=ELEVATED,
        usage_marks=(UsageMark.POETIC,),
        reference=("Gaffiot", "s. v. carpo"),
        status=PROPOSED,
    ),
)


EXAMPLES += (
    Example(
        "{liquide} sūmere",
        Kind.VERB_NOUN,
        "boire (de l’eau, du vin…), prendre une boisson",
        (("fr", "boire"), ("en", "to drink")),
        schema="sumo -obj|nsubj:pass-> {liquide}",
        construction="aquam, uinum sumere",
        realizations=(("aquam sumere", BASE), ("uinum sumere", BASE)),
        reference=("Gaffiot", "s. v. sumo"),
        status=PROPOSED,
    ),
    Example(
        "{possesseur} causā",
        Kind.OPEN_SLOT,
        "pour, en vue de, dans l’intérêt de",
        (("fr", "pour (quelqu’un, quelque chose)"), ("en", "for the sake of")),
        # The possessive adjective depends on causa by det, the genitive by nmod; causa in the
        # ablative leaves out causam Caesaris, « the case of Caesar ».
        schema="causa:abl -nmod|det-> {possesseur}",
        construction="causā après le génitif ou l’adjectif possessif : Caesaris, meā causā",
        realizations=(("Caesaris causā", BASE), ("meā causā", BASE)),
        reference=("Gaffiot", "s. v. causa"),
        status=PROPOSED,
    ),
)


def check_development():
    if not settings.DEBUG:
        raise CommandError(
            gettext("Commande réservée à la machine de développement (DJANGO_DEBUG=True).")
        )


def example_units():
    return Unit.objects.filter(created_by__email=EXAMPLE_AUTHOR)


def example_accounts():
    """The accounts that create and review the examples, created when missing; nobody logs in."""
    accounts = []
    for email, name, role in (
        (EXAMPLE_AUTHOR, "Fiches d’exemple", CONTRIBUTOR),
        (EXAMPLE_REVIEWER, "Relecture des exemples", REVIEWER),
    ):
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(
                email=email, display_name=name, is_adult=True, is_confirmed=True
            )
            user.groups.add(Group.objects.get(name=role))
        accounts.append(user)
    return accounts


def create_example_abstracts(author, reviewer):
    """The abstract words of the examples, created and validated when missing."""
    for name, label, definition, rules in EXAMPLE_ABSTRACTS:
        if AbstractWord.objects.filter(name=name).exists():
            continue
        word = create_abstract_word(
            AbstractWord(name=name, label=label, definition=definition, rules=rules), author
        )
        validate_abstract_word(word, reviewer)


# Finding occurrences

ORDER = ("edition__work__author__birth_year", "edition__work__cts_urn", "position")


class Occurrence(NamedTuple):
    author_id: int
    reference: str
    words: tuple


def _prefixed(prefix, lookups):
    return {f"{prefix}{key}": value for key, value in lookups.items()}


def _first_by_author(rows, authors):
    """Every row, or the first of each author up to ``authors`` authors; a row ends with it."""
    if authors is None:
        return rows
    kept, seen = [], set()
    for row in rows:
        if row[-1] not in seen and len(seen) < authors:
            seen.add(row[-1])
            kept.append(row)
    return kept


def find_occurrences(example, layer, authors=None, exclude=None, **conditions):
    """Occurrences of an example in current editions, in the order of the corpus.

    ``conditions`` and ``exclude`` are lookups on its governing word, or on its last word
    for a unit without schema.
    """
    exclude = exclude or {}
    if example.schema:
        edges = parse_schema(example.schema)
        rows = (
            schema_matches(edges, layer)
            .filter(**_prefixed("token__", conditions))
            .exclude(**_prefixed("token__", exclude))
            .order_by(*(f"token__{field}" for field in ORDER), "part")
            .values_list(
                "token_id",
                "part",
                "token__position",
                "token__passage__reference",
                "token__edition__work__author_id",
            )
        )
        rows = _first_by_author(list(rows), authors)
        words = occurrence_words([row[:3] for row in rows], edges, layer)
        return [Occurrence(row[4], row[3], ids) for row, ids in zip(rows, words, strict=True)]
    *before, last = example.words
    matches = Token.objects.filter(norm=last, edition__is_current=True, **conditions).exclude(
        **exclude
    )
    for offset, word in enumerate(reversed(before), start=1):
        previous = Token.objects.filter(
            edition=OuterRef("edition"), position=OuterRef("position") - offset, norm=word
        )
        matches = matches.filter(Exists(previous))
    rows = matches.order_by(*ORDER).values_list(
        "edition_id", "position", "passage__reference", "edition__work__author_id"
    )
    rows = _first_by_author(list(rows), authors)
    spans = Q(pk__in=[])
    for edition_id, position, _reference, _author in rows:
        spans |= Q(edition_id=edition_id, position__range=(position - len(before), position))
    ids = {
        (edition_id, position): pk
        for pk, edition_id, position in Token.objects.filter(spans).values_list(
            "pk", "edition_id", "position"
        )
    }
    return [
        Occurrence(
            author,
            reference,
            tuple(ids[edition_id, at] for at in range(position - len(before), position + 1)),
        )
        for edition_id, position, reference, author in rows
    ]


# Creating

EXAMPLE, VALIDATE, PROPOSE, AUTOMATIC = "example", "validate", "propose", "automatic"


def plan_attestations(example, focus, layer):
    """(words, what to do) for every occurrence the example keeps.

    In the focus book, occurrences are in turn validated, proposed and left automatic, the
    first one chosen as example; elsewhere in the focus work they stay automatic. In the rest
    of the core, the first author's occurrence is a validated example, the others automatic;
    outside the core, all are automatic (T2). With no attestation to propose, the first
    occurrence is proposed, since a unit is created with one.
    """
    in_focus = find_occurrences(example, layer, edition__work=focus)
    book = [
        occurrence.words for occurrence in in_focus if occurrence.reference.startswith(FOCUS_BOOK)
    ]
    plan = [
        (words, (EXAMPLE if index == 0 else VALIDATE, PROPOSE, AUTOMATIC)[index % 3])
        for index, words in enumerate(book)
    ]
    plan += [
        (occurrence.words, AUTOMATIC)
        for occurrence in in_focus
        if not occurrence.reference.startswith(FOCUS_BOOK)
    ]
    others = find_occurrences(
        example,
        layer,
        authors=OTHER_AUTHORS,
        exclude={"edition__work__author": focus.author_id},
        edition__work__is_core=True,
    )
    plan += [
        (occurrence.words, EXAMPLE if index == 0 else AUTOMATIC)
        for index, occurrence in enumerate(others)
    ]
    outside = find_occurrences(
        example, layer, authors=OUTSIDE_AUTHORS, edition__work__is_core=False
    )
    plan += [(occurrence.words, AUTOMATIC) for occurrence in outside]
    if plan and all(action == AUTOMATIC for _words, action in plan):
        plan[0] = (plan[0][0], PROPOSE)
    return plan


def _evidence(words):
    return corpus_evidence(",".join(str(pk) for pk in words))


@transaction.atomic
def create_example(example, focus, layer, author, reviewer):
    """Create an example unit with its parts and attestations; None if the corpus lacks it."""
    plan = plan_attestations(example, focus, layer)
    if not plan:
        return None
    first = next(index for index, (_words, action) in enumerate(plan) if action != AUTOMATIC)
    unit = Unit(
        reference_form=example.reference_form,
        kind=example.kind,
        schema=example.schema,
        construction=example.construction,
        register=example.register,
        usage_marks=list(example.usage_marks),
    )
    create_unit(unit, author, example.definition, [_evidence(plan[first][0])])
    sense = unit.senses.get()
    for language, expression in example.equivalents:
        save_part(Equivalent(sense=sense, language=language, expression=expression), author)
    for form, variation in example.realizations:
        save_part(Realization(unit=unit, form=form, variation=variation), author)
    if example.reference:
        abbreviation, locator = example.reference
        work = BibliographicWork.objects.get(abbreviation=abbreviation)
        save_part(UnitReference(unit=unit, work=work, locator=locator), author)
    manual = [
        _evidence(words)
        for index, (words, action) in enumerate(plan)
        if action != AUTOMATIC and index != first
    ]
    add_attestations(unit, manual, author)
    automatic = [words for words, action in plan if action == AUTOMATIC]
    record_automatic_attestations(unit, automatic, author)
    refresh_frequency(unit)
    if example.status != DRAFT:
        propose_unit(unit, author)
        unit.refresh_from_db()
        by_words = {
            frozenset(token.pk for token in attestation.tokens.all()): attestation
            for attestation in unit.attestations.prefetch_related("tokens")
        }
        chosen = [by_words[frozenset(words)] for words, action in plan if action == EXAMPLE]
        checked = [by_words[frozenset(words)] for words, action in plan if action == VALIDATE]
        ids = [attestation.pk for attestation in chosen + checked]
        review_attestations(unit, ids, reviewer, Attestation.Status.VALIDATED)
        for attestation in chosen:
            attestation.refresh_from_db()
            set_example(attestation, author, True)
    if example.status == VALIDATED:
        validate_unit(unit, reviewer)
    unit.refresh_from_db()
    return unit


def attestation_counts(unit):
    """Attestations of a unit: validated, proposed by people, found automatically."""
    attestations = unit.attestations.active()
    return {
        "validated": attestations.filter(status=Attestation.Status.VALIDATED).count(),
        "proposed": attestations.filter(
            level=Attestation.Level.VALIDATED, status=Attestation.Status.PROPOSED
        ).count(),
        "automatic": attestations.filter(level=Attestation.Level.AUTOMATIC).count(),
    }


# Deleting


class ExamplesInUse(Exception):
    """Contents outside the examples point to them: deleting the examples would break them."""

    def __init__(self, links):
        super().__init__(links)
        self.links = links


def links_from_other_contents(unit_ids):
    attestations = Attestation.objects.filter(unit_id__in=unit_ids)
    links = {
        "justifications": Justification.objects.filter(units__in=unit_ids).distinct().count(),
        "evidences": Evidence.objects.filter(attestation__in=attestations).count(),
        "sightings": Attestation.sightings.rel.related_model.objects.filter(
            attestation__in=attestations
        ).count(),
        "relations": UnitRelation.objects.filter(target_id__in=unit_ids)
        .exclude(unit_id__in=unit_ids)
        .count(),
        "abstract_words": _units_using_example_abstracts().exclude(pk__in=unit_ids).count(),
    }
    return {name: count for name, count in links.items() if count}


def _example_abstracts():
    return AbstractWord.objects.filter(created_by__email=EXAMPLE_AUTHOR)


def _units_using_example_abstracts():
    """Units whose schema or reference form names an abstract word of the examples."""
    condition = Q(pk__in=[])
    for word in _example_abstracts():
        condition |= Q(schema__contains=str(word)) | Q(reference_form__contains=str(word))
    return Unit.objects.filter(condition)


def _delete_records(model, pks):
    """Remove the history, messages, votes and reports of contents about to be deleted."""
    if not pks:
        return
    about = {"content_type": ContentType.objects.get_for_model(model), "object_id__in": pks}
    comments = list(Comment.objects.filter(**about).values_list("pk", flat=True))
    _delete_records(Comment, comments)
    Comment.objects.filter(pk__in=comments).delete()
    revisions = Revision.objects.filter(**about)
    revisions.update(reverted_to=None)
    revisions.delete()
    Vote.objects.filter(**about).delete()
    Report.objects.filter(**about).delete()


# Parts first: a doubt points to an attestation, an attestation to a sense and a realization,
# an equivalent to a sense.
PARTS = (
    (Attestation.doubts.rel.related_model, "attestation__unit_id__in"),
    (Attestation, "unit_id__in"),
    (Equivalent, "sense__unit_id__in"),
    (Realization, "unit_id__in"),
    (Sense, "unit_id__in"),
    (UnitRelation, "unit_id__in"),
    (UnitReference, "unit_id__in"),
)


@transaction.atomic
def delete_examples():
    """Delete the example units, their parts, their history and the example accounts."""
    unit_ids = list(example_units().values_list("pk", flat=True))
    links = links_from_other_contents(unit_ids)
    if links:
        raise ExamplesInUse(links)
    counts = {"units": len(unit_ids), "attestations": 0, "parts": 0}
    for model, lookup in PARTS:
        objects = model.objects.filter(**{lookup: unit_ids})
        pks = list(objects.values_list("pk", flat=True))
        _delete_records(model, pks)
        objects.delete()
        counts["attestations" if model is Attestation else "parts"] += len(pks)
    counts["candidates"] = Candidate.objects.filter(unit_id__in=unit_ids).update(
        status=Candidate.Status.PENDING, unit=None, decided_by=None, decided_at=None
    )
    _delete_records(Unit, unit_ids)
    Unit.objects.filter(pk__in=unit_ids).delete()
    words = list(_example_abstracts().values_list("pk", flat=True))
    _delete_records(AbstractWord, words)
    AbstractWord.objects.filter(pk__in=words).delete()
    counts["abstract_words"] = len(words)
    counts["accounts"] = 0
    for user in User.objects.filter(email__in=(EXAMPLE_AUTHOR, EXAMPLE_REVIEWER)):
        try:
            with transaction.atomic():
                user.delete()
        except ProtectedError:
            continue
        counts["accounts"] += 1
    return counts
