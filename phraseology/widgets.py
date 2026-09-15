"""The drawing of a schema: words linked by syntactic relations, written into the schema field."""

from django import forms
from django.urls import reverse

from .schema import CASE_CHOICES, MAX_RELATIONS, RELATION_CHOICES


class SchemaWidget(forms.TextInput):
    """The written schema, followed by what the script needs to draw it.

    Without script, only the text field shows. ``words_from`` names the field whose words become
    the labels to link; ``slot`` offers the open slot of queries; ``count`` shows the occurrences
    of the schema in the core while it is drawn.
    """

    template_name = "phraseology/widgets/schema.html"

    def __init__(self, attrs=None, words_from="", slot=False, count=False):
        defaults = {"lang": "la", "spellcheck": "false", "autocomplete": "off"}
        super().__init__(defaults | (attrs or {}))
        self.words_from = words_from
        self.slot = slot
        self.count = count

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        relations = [
            {"code": code, "label": str(label), "common": common}
            for code, label, common in RELATION_CHOICES
        ]
        context["builder"] = {
            "words_from": self.words_from,
            "slot": self.slot,
            "count": self.count,
            "max_relations": MAX_RELATIONS,
            "lemmas_url": reverse("phraseology:schema_lemmas"),
            "check_url": reverse("phraseology:schema_check"),
            "units_url": reverse("phraseology:schema_units"),
            "common": [relation for relation in relations if relation["common"]],
            "others": [relation for relation in relations if not relation["common"]],
            "cases": [{"code": code, "label": str(label)} for code, label in CASE_CHOICES],
        }
        return context
