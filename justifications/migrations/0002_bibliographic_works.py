"""A first list of grammars and dictionaries; administrators complete and correct it.

Works whose rights status is uncertain are marked as under copyright: they are cited only.
"""

from django.db import migrations

WORKS = [
    ("A&G", "Allen & Greenough, New Latin Grammar (1903)", "grammar", "free"),
    ("G&L", "Gildersleeve & Lodge, Latin Grammar (1895)", "grammar", "free"),
    ("K-St", "Kühner & Stegmann, Ausführliche Grammatik der lateinischen Sprache", "grammar", "restricted"),
    ("E-T", "Ernout & Thomas, Syntaxe latine", "grammar", "restricted"),
    ("H-Sz", "Hofmann & Szantyr, Lateinische Syntax und Stilistik", "grammar", "restricted"),
    ("Menge", "Menge, Burkard & Schauer, Lehrbuch der lateinischen Syntax und Semantik", "grammar", "restricted"),
    ("Pinkster", "Pinkster, The Oxford Latin Syntax", "grammar", "restricted"),
    ("Woodcock", "Woodcock, A New Latin Syntax", "grammar", "restricted"),
    ("Gaffiot", "Gaffiot, Dictionnaire illustré latin-français (1934)", "dictionary", "free"),
    ("L&S", "Lewis & Short, A Latin Dictionary (1879)", "dictionary", "free"),
    ("Georges", "Georges, Ausführliches lateinisch-deutsches Handwörterbuch", "dictionary", "restricted"),
    ("OLD", "Oxford Latin Dictionary", "dictionary", "restricted"),
    ("TLL", "Thesaurus Linguae Latinae", "dictionary", "restricted"),
    ("LRL", "Lexicon recentis Latinitatis", "dictionary", "restricted"),
]  # fmt: skip


def add_works(apps, schema_editor):
    BibliographicWork = apps.get_model("justifications", "BibliographicWork")
    for abbreviation, title, kind, rights in WORKS:
        BibliographicWork.objects.get_or_create(
            abbreviation=abbreviation, defaults={"title": title, "kind": kind, "rights": rights}
        )


class Migration(migrations.Migration):
    dependencies = [("justifications", "0001_initial")]

    operations = [migrations.RunPython(add_works, migrations.RunPython.noop)]
