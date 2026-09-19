"""Abstract words: classes of words a node of a schema may stand for.

``sumo -obj-> {liquide}`` finds *aquam sumere* and *potionem sumere*: {liquide} is a class
whose rules list lemmas. ``causa -nmod-> {possesseur}`` finds *Caesaris causa* and *mea causa*:
one rule takes nouns and pronouns in the genitive, another the possessive adjectives.

A rule is a dict of three lists: parts of speech, features and lemmas; a word meets the rule
when it meets each list that is not empty, and belongs to the class when it meets one rule.
Features come from a closed list, so that looking for them in the features of the analysis
(``Case=Gen`` in ``Case=Gen|Number=Sing``) finds nothing else.

Neither the parts of speech nor the features of the analysis are indexed: an abstract word is
never the root of a schema, which is looked for by its lemma, and its words are found among the
dependents of a word already found.
"""

import re

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from corpus.text import normalize

MAX_RULES = 4
MAX_LEMMAS = 40
MAX_NAME_LENGTH = 40
NAME = re.compile(r"[a-z]+(?:-[a-z]+)*")
# An abstract word as written in a schema or a reference form.
WRITTEN = re.compile(r"\{([^{}\[\];]*)\}")

# Universal Dependencies parts of speech, as the reader reads them.
PARTS_OF_SPEECH = {
    "ADJ": _("adjectif"),
    "ADP": _("préposition"),
    "ADV": _("adverbe"),
    "AUX": _("auxiliaire"),
    "CCONJ": _("conjonction de coordination"),
    "DET": _("déterminant"),
    "INTJ": _("interjection"),
    "NOUN": _("nom commun"),
    "NUM": _("numéral"),
    "PART": _("particule"),
    "PRON": _("pronom"),
    "PROPN": _("nom propre"),
    "PUNCT": _("ponctuation"),
    "SCONJ": _("conjonction de subordination"),
    "SYM": _("symbole"),
    "VERB": _("verbe"),
    "X": _("autre"),
}
# The parts of speech a rule may take, the common ones first.
RULE_PARTS_OF_SPEECH = (
    "NOUN",
    "PROPN",
    "PRON",
    "ADJ",
    "DET",
    "VERB",
    "ADV",
    "NUM",
    "ADP",
    "AUX",
    "CCONJ",
    "SCONJ",
    "PART",
    "INTJ",
)
# The features a rule may take, by feature: (value as the analysis writes it, label).
FEATURES = {
    "Case": (
        _("Cas"),
        (
            ("Case=Nom", _("nominatif")),
            ("Case=Voc", _("vocatif")),
            ("Case=Acc", _("accusatif")),
            ("Case=Gen", _("génitif")),
            ("Case=Dat", _("datif")),
            ("Case=Abl", _("ablatif")),
        ),
    ),
    "Number": (_("Nombre"), (("Number=Sing", _("singulier")), ("Number=Plur", _("pluriel")))),
    "Gender": (
        _("Genre"),
        (
            ("Gender=Masc", _("masculin")),
            ("Gender=Fem", _("féminin")),
            ("Gender=Neut", _("neutre")),
        ),
    ),
}
FEATURE_LABELS = {value: label for _name, choices in FEATURES.values() for value, label in choices}


def clean_name(name):
    """The name of an abstract word, written as it is compared; raise ValidationError if not
    made of lower-case letters and hyphens."""
    name = (name or "").strip().strip("{}").strip().lower()
    if not NAME.fullmatch(name) or len(name) > MAX_NAME_LENGTH:
        raise ValidationError(
            gettext(
                "Le nom d’un mot abstrait s’écrit en lettres minuscules sans accents, avec des "
                "traits d’union au besoin : liquide, nom-de-lieu."
            ),
            code="abstract_name",
        )
    return name


def clean_rule(rule):
    """A rule with its lists checked and in order; empty lists stay empty."""
    upos = [code for code in RULE_PARTS_OF_SPEECH if code in (rule.get("upos") or [])]
    feats = [value for value in FEATURE_LABELS if value in (rule.get("feats") or [])]
    lemmas = list(dict.fromkeys(normalize(lemma) for lemma in rule.get("lemmas") or []))
    if any(not lemma.isalpha() for lemma in lemmas):
        raise ValidationError(
            gettext("Un lemme s’écrit en un seul mot, avec des lettres seulement."),
            code="abstract_lemma",
        )
    if len(lemmas) > MAX_LEMMAS:
        raise ValidationError(
            gettext("Une ligne compte au plus %(limit)d lemmes.") % {"limit": MAX_LEMMAS},
            code="abstract_lemmas",
        )
    for label, choices in FEATURES.values():
        if sum(value in feats for value, _label in choices) > 1:
            raise ValidationError(
                gettext("Une ligne ne prend qu’une valeur par trait : %(feature)s.")
                % {"feature": label.lower()},
                code="abstract_feature",
            )
    return {"upos": upos, "feats": feats, "lemmas": lemmas}


def is_empty(rule):
    return not (rule.get("upos") or rule.get("feats") or rule.get("lemmas"))


def clean_rules(rules):
    """The rules of an abstract word, empty ones left out; raise ValidationError if none."""
    cleaned = [clean_rule(rule) for rule in rules if not is_empty(rule)]
    if not cleaned:
        raise ValidationError(
            gettext(
                "Remplissez au moins une ligne : une catégorie, un trait ou une liste de lemmes."
            ),
            code="abstract_rules",
        )
    if len(cleaned) > MAX_RULES:
        raise ValidationError(
            gettext("Un mot abstrait compte au plus %(limit)d lignes.") % {"limit": MAX_RULES},
            code="abstract_too_many_rules",
        )
    return cleaned


def rule_condition(rule):
    """Conditions on the analysis of a word: it meets the rule."""
    condition = Q()
    if rule.get("upos"):
        condition &= Q(upos__in=rule["upos"])
    for value in rule.get("feats") or []:
        condition &= Q(feats__contains=value)
    if rule.get("lemmas"):
        condition &= Q(lemma_norm__in=rule["lemmas"])
    return condition


def word_condition(word):
    """Conditions on the analysis of a word: it belongs to the abstract word, hidden or missing
    words matching nothing."""
    condition = Q(pk__in=[])
    if word is None or word.is_hidden:
        return condition
    for rule in word.rules:
        if not is_empty(rule):
            condition |= rule_condition(rule)
    return condition


def word_lemmas(word):
    """The lemmas of an abstract word when every rule lists its lemmas, otherwise None: a word
    of the class is then not known by its lemma alone."""
    rules = [rule for rule in word.rules if not is_empty(rule)]
    if not rules or any(not rule.get("lemmas") for rule in rules):
        return None
    return list(dict.fromkeys(lemma for rule in rules for lemma in rule["lemmas"]))


def rule_label(rule):
    """A rule as the reader reads it: « nom commun ou pronom, génitif ; meus, tuus »."""
    parts = []
    if rule.get("upos"):
        names = [str(PARTS_OF_SPEECH.get(code, code)) for code in rule["upos"]]
        parts.append(
            names[0]
            if len(names) == 1
            else gettext("%(first)s ou %(last)s")
            % {"first": ", ".join(names[:-1]), "last": names[-1]}
        )
    if rule.get("feats"):
        parts.append(", ".join(str(FEATURE_LABELS.get(value, value)) for value in rule["feats"]))
    label = ", ".join(parts)
    if rule.get("lemmas"):
        lemmas = ", ".join(rule["lemmas"])
        label = f"{label} ; {lemmas}" if label else lemmas
    return label


def _words(names):
    # The models read schemas, which read the names of abstract words here.
    from .models import AbstractWord

    return {word.name: word for word in AbstractWord.objects.filter(name__in=names)}


def abstract_conditions(edges):
    """Conditions on the analysis of a word for each abstract word of a schema, by node:
    {"{liquide}": Q(...)}. A missing or hidden word matches nothing."""
    from .schema import schema_abstracts

    names = schema_abstracts(edges)
    words = _words(names) if names else {}
    return {f"{{{name}}}": word_condition(words.get(name)) for name in names}


def check_abstract_names(names):
    """The abstract words of these names; raise ValidationError if one is unknown or hidden."""
    words = _words(names) if names else {}
    missing = [name for name in names if name not in words or words[name].is_hidden]
    if missing:
        raise ValidationError(
            gettext(
                "Mot abstrait inconnu : %(names)s. Proposez-le d’abord dans la liste des mots "
                "abstraits."
            )
            % {"names": ", ".join(f"{{{name}}}" for name in missing)},
            code="abstract_unknown",
        )
    return [words[name] for name in names]


def check_abstract_words(edges):
    """The abstract words of a schema; raise ValidationError if one is unknown or hidden."""
    from .schema import schema_abstracts

    return check_abstract_names(schema_abstracts(edges))
