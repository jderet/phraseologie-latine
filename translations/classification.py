"""Closed vocabularies that classify a source text: its genres (what the text is) and its
themes (what it speaks of). Choice of 20 September 2026.

The genres are those of modern texts, not those of the Latin corpus (``corpus.models.Work``):
an article of the press or a manifesto has no ancient counterpart. Science fiction, detective
stories and the fantastic are themes, not genres.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

# A text is classified, not described: a few genres and a few themes at most.
MAX_GENRES = 3
MAX_THEMES = 6


class Genre(models.TextChoices):
    """What the text is."""

    # Stories
    NOVEL = "roman", _("roman")
    SHORT_STORY = "nouvelle", _("nouvelle")
    TALE = "conte", _("conte")
    MYTH = "mythe-legende", _("mythe et légende")
    TRAVEL = "recit-voyage", _("récit de voyage")
    HISTORICAL = "recit-historique", _("récit historique")
    MEMOIRS = "memoires", _("mémoires et autobiographie")
    BIOGRAPHY = "biographie", _("biographie")
    DIARY = "journal-intime", _("journal intime")
    CHILDREN = "jeunesse", _("littérature de jeunesse")

    # Ideas
    ESSAY = "essai", _("essai")
    DIALOGUE = "dialogue-philosophique", _("dialogue philosophique")
    TREATISE = "traite", _("traité")
    ENCYCLOPEDIA = "encyclopedie", _("article encyclopédique")
    SCIENTIFIC = "texte-scientifique", _("texte scientifique")
    TECHNICAL = "texte-technique", _("texte technique")
    LEGAL = "texte-juridique", _("texte juridique")
    RELIGIOUS = "texte-religieux", _("texte religieux et sermon")
    MANIFESTO = "manifeste", _("manifeste politique")
    PAMPHLET = "pamphlet", _("pamphlet")
    CRITICISM = "critique-litteraire", _("critique littéraire")

    # Press
    ARTICLE = "article-presse", _("article de presse")
    COLUMN = "chronique", _("chronique")
    REPORT = "reportage", _("reportage")
    INTERVIEW = "entretien", _("entretien")

    # Spoken word
    LETTER = "lettre", _("lettre")
    SPEECH = "discours-politique", _("discours politique")
    PLEADING = "plaidoirie", _("plaidoirie")
    EULOGY = "oraison-funebre", _("oraison funèbre")
    PREFACE = "preface", _("préface et dédicace")
    LECTURE = "conference", _("conférence")

    # Short forms
    FABLE = "fable", _("fable")
    APOLOGUE = "apologue", _("apologue")
    MAXIM = "maxime", _("maxime et aphorisme")
    PROVERB = "proverbe", _("proverbe")
    ANECDOTE = "anecdote", _("anecdote")
    EPIGRAM = "epigramme", _("épigramme")
    RIDDLE = "devinette", _("devinette")

    # Theatre
    COMEDY = "comedie", _("comédie")
    TRAGEDY = "tragedie", _("tragédie")
    DRAMA = "drame", _("drame")
    SCREENPLAY = "scenario", _("scénario et dialogue de fiction")

    # Poetry
    LYRIC = "poeme-lyrique", _("poème lyrique")
    EPIC = "poeme-epique", _("poème épique")
    DIDACTIC = "poeme-didactique", _("poème didactique")
    SONG = "chanson", _("chanson")
    HYMN = "hymne", _("hymne")
    VERSE_SATIRE = "satire-vers", _("satire en vers")

    # Everyday writing
    INSTRUCTIONS = "mode-emploi", _("recette et mode d’emploi")
    ADVERTISEMENT = "annonce", _("annonce et publicité")
    RULES = "reglement", _("guide et règlement")
    ORDINARY_LETTER = "correspondance-ordinaire", _("correspondance ordinaire")


class Theme(models.TextChoices):
    """What the text speaks of."""

    # The city
    WAR = "guerre", _("guerre et armée")
    POLITICS = "politique", _("politique et pouvoir")
    JUSTICE = "justice", _("justice et lois")
    FREEDOM = "liberte", _("liberté et servitude")
    SOCIETY = "societe", _("foule et société")
    MONEY = "argent", _("argent et commerce")
    WORK = "travail", _("travail et métiers")

    # The mind
    PHILOSOPHY = "philosophie", _("philosophie et morale")
    RELIGION = "religion", _("religion et dieux")
    SCIENCE = "science", _("science et savoir")
    EDUCATION = "education", _("éducation et enfance")
    LANGUAGE = "langue", _("langue et écriture")
    HISTORY = "histoire", _("histoire et mémoire")
    IDENTITY = "identite", _("identité et soi")

    # A life
    LOVE = "amour", _("amour")
    FRIENDSHIP = "amitie", _("amitié")
    FAMILY = "famille", _("famille")
    DEATH = "mort", _("mort et deuil")
    OLD_AGE = "vieillesse", _("vieillesse et temps qui passe")
    BODY = "corps", _("corps et santé")
    VIOLENCE = "violence", _("peur et violence")
    EVERYDAY = "vie-quotidienne", _("vie quotidienne")

    # The world
    NATURE = "nature", _("nature et paysages")
    ANIMALS = "animaux", _("animaux")
    SEA = "mer", _("mer et navigation")
    TRAVEL = "voyage", _("voyage et exil")
    TOWN = "ville-campagne", _("ville et campagne")
    SKY = "ciel", _("ciel et astres")
    SEASONS = "saisons", _("saisons et climat")

    # Pleasures
    FOOD = "nourriture", _("nourriture et banquet")
    FEAST = "fete", _("fête et jeux")
    SPORT = "sport", _("sport")
    ART = "art", _("art et beauté")
    MUSIC = "musique", _("musique")
    HUMOUR = "humour", _("humour et satire")
    WONDER = "merveilleux", _("rêve et merveilleux")

    # Today
    MACHINES = "machines", _("techniques et machines")
    COMPUTING = "informatique", _("informatique et réseaux")
    MEDICINE = "medecine", _("médecine moderne")
    ECOLOGY = "ecologie", _("écologie")
    ECONOMY = "economie", _("économie contemporaine")

    # Imagination
    SCIENCE_FICTION = "science-fiction", _("science-fiction")
    DETECTIVE = "policier", _("policier")
    FANTASTIC = "fantastique", _("fantastique")


# Families, to show the long lists in an orderly way. Every value belongs to one family, and
# a test checks it.
GENRE_GROUPS = (
    (
        _("Récits"),
        (
            Genre.NOVEL,
            Genre.SHORT_STORY,
            Genre.TALE,
            Genre.MYTH,
            Genre.TRAVEL,
            Genre.HISTORICAL,
            Genre.MEMOIRS,
            Genre.BIOGRAPHY,
            Genre.DIARY,
            Genre.CHILDREN,
        ),
    ),
    (
        _("Idées"),
        (
            Genre.ESSAY,
            Genre.DIALOGUE,
            Genre.TREATISE,
            Genre.ENCYCLOPEDIA,
            Genre.SCIENTIFIC,
            Genre.TECHNICAL,
            Genre.LEGAL,
            Genre.RELIGIOUS,
            Genre.MANIFESTO,
            Genre.PAMPHLET,
            Genre.CRITICISM,
        ),
    ),
    (_("Presse"), (Genre.ARTICLE, Genre.COLUMN, Genre.REPORT, Genre.INTERVIEW)),
    (
        _("Parole"),
        (
            Genre.LETTER,
            Genre.SPEECH,
            Genre.PLEADING,
            Genre.EULOGY,
            Genre.PREFACE,
            Genre.LECTURE,
        ),
    ),
    (
        _("Formes brèves"),
        (
            Genre.FABLE,
            Genre.APOLOGUE,
            Genre.MAXIM,
            Genre.PROVERB,
            Genre.ANECDOTE,
            Genre.EPIGRAM,
            Genre.RIDDLE,
        ),
    ),
    (_("Théâtre"), (Genre.COMEDY, Genre.TRAGEDY, Genre.DRAMA, Genre.SCREENPLAY)),
    (
        _("Poésie"),
        (
            Genre.LYRIC,
            Genre.EPIC,
            Genre.DIDACTIC,
            Genre.SONG,
            Genre.HYMN,
            Genre.VERSE_SATIRE,
        ),
    ),
    (
        _("Vie courante"),
        (Genre.INSTRUCTIONS, Genre.ADVERTISEMENT, Genre.RULES, Genre.ORDINARY_LETTER),
    ),
)

THEME_GROUPS = (
    (
        _("Cité"),
        (
            Theme.WAR,
            Theme.POLITICS,
            Theme.JUSTICE,
            Theme.FREEDOM,
            Theme.SOCIETY,
            Theme.MONEY,
            Theme.WORK,
        ),
    ),
    (
        _("Esprit"),
        (
            Theme.PHILOSOPHY,
            Theme.RELIGION,
            Theme.SCIENCE,
            Theme.EDUCATION,
            Theme.LANGUAGE,
            Theme.HISTORY,
            Theme.IDENTITY,
        ),
    ),
    (
        _("Vie"),
        (
            Theme.LOVE,
            Theme.FRIENDSHIP,
            Theme.FAMILY,
            Theme.DEATH,
            Theme.OLD_AGE,
            Theme.BODY,
            Theme.VIOLENCE,
            Theme.EVERYDAY,
        ),
    ),
    (
        _("Monde"),
        (
            Theme.NATURE,
            Theme.ANIMALS,
            Theme.SEA,
            Theme.TRAVEL,
            Theme.TOWN,
            Theme.SKY,
            Theme.SEASONS,
        ),
    ),
    (
        _("Plaisirs"),
        (
            Theme.FOOD,
            Theme.FEAST,
            Theme.SPORT,
            Theme.ART,
            Theme.MUSIC,
            Theme.HUMOUR,
            Theme.WONDER,
        ),
    ),
    (
        _("Aujourd’hui"),
        (Theme.MACHINES, Theme.COMPUTING, Theme.MEDICINE, Theme.ECOLOGY, Theme.ECONOMY),
    ),
    (_("Imaginaire"), (Theme.SCIENCE_FICTION, Theme.DETECTIVE, Theme.FANTASTIC)),
)


def grouped_choices(groups):
    """Choices by family, as Django renders them: <optgroup> in a menu, a titled block of
    checkboxes in a form."""
    return [(name, [(value, value.label) for value in values]) for name, values in groups]


def clean_codes(codes, choices):
    """The known codes only, in the order of the list, without repetition."""
    wanted = set(codes or ())
    return [code for code in choices.values if code in wanted]


def names(codes, choices):
    """(code, label) pairs of the codes, in the order of the list."""
    labels = dict(choices.choices)
    return [(code, labels[code]) for code in clean_codes(codes, choices)]
