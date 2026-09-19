from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from corpus.models import TokenAnalysis
from moderation.models import Revision
from moderation.services import hide_content, revert_to
from phraseology.abstract import clean_name, clean_rules, rule_label, word_condition, word_lemmas
from phraseology.models import AbstractWord, Unit, UnitForm
from phraseology.services import (
    current_frequency,
    missing_fields,
    refresh_frequency,
    update_abstract_word,
    update_unit,
    validate_abstract_word,
)

from .factories import LIQUID, OWNER, analyze, make_abstract_word, set_status
from .test_frequency import AnalysedCorpusTestCase
from .test_units import PhraseologyTestCase


class RulesTests(SimpleTestCase):
    def test_names(self):
        self.assertEqual(clean_name(" {Liquide} "), "liquide")
        self.assertEqual(clean_name("nom-de-lieu"), "nom-de-lieu")
        for name in ("", "liquidé", "deux mots", "liquide2", "-a", "a" * 41):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                clean_name(name)

    def test_rules_are_cleaned_and_empty_lines_left_out(self):
        rules = clean_rules(
            [
                {"upos": ["PRON", "NOUN", "XYZ"], "feats": ["Case=Gen", "Bad=1"], "lemmas": []},
                {"upos": [], "feats": [], "lemmas": []},
                {"lemmas": ["Vīnum", "aqua", "aqua"]},
            ]
        )
        self.assertEqual(
            rules,
            [
                {"upos": ["NOUN", "PRON"], "feats": ["Case=Gen"], "lemmas": []},
                {"upos": [], "feats": [], "lemmas": ["uinum", "aqua"]},
            ],
        )

    def test_invalid_rules(self):
        cases = {
            "abstract_rules": [{"upos": [], "feats": [], "lemmas": []}],
            "abstract_lemma": [{"lemmas": ["aqua fons"]}],
            "abstract_feature": [{"feats": ["Case=Gen", "Case=Dat"]}],
            "abstract_lemmas": [{"lemmas": [f"a{'b' * n}" for n in range(41)]}],
            "abstract_too_many_rules": [{"lemmas": ["aqua"]}] * 5,
        }
        for code, rules in cases.items():
            with self.subTest(code=code), self.assertRaises(ValidationError) as caught:
                clean_rules(rules)
            self.assertEqual(caught.exception.code, code)

    def test_labels(self):
        self.assertEqual(
            [rule_label(rule) for rule in OWNER],
            ["nom commun, nom propre ou pronom, génitif", "meus, tuus, suus, noster, uester"],
        )

    def test_lemmas_when_every_rule_lists_them(self):
        self.assertEqual(word_lemmas(AbstractWord(rules=LIQUID)), ["aqua", "uinum", "potio"])
        self.assertIsNone(word_lemmas(AbstractWord(rules=OWNER)))


class WordConditionTests(AnalysedCorpusTestCase):
    """Words of the fixture: capio, consilium, bonus; a genitive and a possessive are added."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _consilium, _cepit, ut, abiret = cls.words
        analyze(cls.layer, ut, "caesar", upos="PROPN", feats="Case=Gen|Number=Sing")
        analyze(cls.layer, abiret, "meus", upos="DET", feats="Case=Abl|Number=Sing")

    def lemmas(self, rules):
        word = AbstractWord(rules=rules)
        found = TokenAnalysis.objects.filter(word_condition(word), layer=self.layer)
        return sorted(set(found.values_list("lemma_norm", flat=True)))

    def test_every_condition_of_a_line_and_any_line(self):
        self.assertEqual(self.lemmas(OWNER), ["caesar", "meus"])
        self.assertEqual(self.lemmas(OWNER[:1]), ["caesar"])
        self.assertEqual(
            self.lemmas([{"upos": ["NOUN"], "feats": [], "lemmas": []}]), ["consilium"]
        )
        self.assertEqual(
            self.lemmas([{"upos": ["ADJ"], "feats": [], "lemmas": ["bonus"]}]), ["bonus"]
        )
        self.assertEqual(self.lemmas([{"upos": ["NOUN"], "feats": [], "lemmas": ["bonus"]}]), [])

    def test_a_hidden_word_or_no_rule_finds_nothing(self):
        self.assertEqual(self.lemmas([]), [])
        word = make_abstract_word(self.author, rules=OWNER)
        hide_content(word, self.reviewer)
        word.refresh_from_db()
        self.assertFalse(TokenAnalysis.objects.filter(word_condition(word)).exists())


class AbstractWordTests(PhraseologyTestCase):
    def test_proposed_then_validated_by_a_reviewer(self):
        word = make_abstract_word(self.author)
        self.assertEqual((word.status, str(word)), (AbstractWord.Status.PROPOSED, "{liquide}"))
        with self.assertRaises(PermissionDenied):
            validate_abstract_word(word, self.other)
        validate_abstract_word(word, self.reviewer)
        word.refresh_from_db()
        self.assertEqual((word.status, word.validated_by), ("validated", self.reviewer))

    def test_any_active_account_completes_it_and_a_revert_restores_every_rule(self):
        word = make_abstract_word(self.author)
        first = Revision.objects.for_object(word).get()
        word.rules = [{"upos": ["NOUN"], "feats": ["Case=Gen"], "lemmas": []}]
        update_abstract_word(word, self.other)
        revert_to(first, self.reviewer)
        word.refresh_from_db()
        self.assertEqual(word.rules, LIQUID)


class AbstractWordPagesTests(PhraseologyTestCase):
    def post_form(self, url, **data):
        fields = {"name": "possesseur", "label": "possesseur", "definition": ""}
        return self.client.post(url, {**fields, **data})

    def test_create_from_the_form(self):
        self.client.force_login(self.author)
        url = reverse("phraseology:abstract_word_create")
        self.assertContains(self.client.get(url), "Ligne 4")
        page = self.post_form(url)
        self.assertContains(page, "Remplissez au moins une ligne")
        page = self.post_form(
            url,
            upos1=["NOUN", "PRON"],
            case1="Case=Gen",
            lemmas2="meus, tuus;suus  noster",
        )
        word = AbstractWord.objects.get(name="possesseur")
        self.assertRedirects(page, word.get_absolute_url())
        self.assertEqual(
            word.rules,
            [
                {"upos": ["NOUN", "PRON"], "feats": ["Case=Gen"], "lemmas": []},
                {"upos": [], "feats": [], "lemmas": ["meus", "tuus", "suus", "noster"]},
            ],
        )
        page = self.post_form(url, lemmas1="aqua")
        self.assertContains(page, "Un mot abstrait porte déjà ce nom.")

    def test_the_name_does_not_change(self):
        word = make_abstract_word(self.author)
        self.client.force_login(self.other)
        url = reverse("phraseology:abstract_word_edit", args=[word.pk])
        page = self.client.get(url)
        self.assertContains(page, "aqua, uinum, potio")
        self.post_form(url, name="boisson", label="nom de liquide", lemmas1="aqua, lac")
        word.refresh_from_db()
        self.assertEqual((word.name, word.label), ("liquide", "nom de liquide"))
        self.assertEqual(word.rules[0]["lemmas"], ["aqua", "lac"])

    def test_list_and_page(self):
        word = make_abstract_word(self.author, rules=OWNER, label="possesseur")
        page = self.client.get(reverse("phraseology:abstract_word_list"), {"q": "possess"})
        self.assertContains(page, "{liquide}")
        self.assertContains(page, "meus, tuus")
        page = self.client.get(word.get_absolute_url())
        self.assertContains(page, "nom commun, nom propre ou pronom, génitif")
        self.assertContains(page, "Aucune fiche ne l’emploie encore.")
        self.assertNotContains(page, "Valider le mot abstrait")
        self.client.force_login(self.reviewer)
        self.client.post(reverse("phraseology:abstract_word_validate", args=[word.pk]))
        word.refresh_from_db()
        self.assertEqual(word.status, AbstractWord.Status.VALIDATED)

    def test_signing_in_is_needed_to_propose(self):
        page = self.client.get(reverse("phraseology:abstract_word_create"))
        self.assertEqual(page.status_code, 302)


class AbstractWordInSchemaTests(PhraseologyTestCase):
    def test_the_schema_of_a_unit_names_a_known_word(self):
        self.client.force_login(self.author)
        url = reverse("phraseology:unit_edit", args=[self.unit.pk])
        page = self.client.get(url)
        data = {
            key: value
            for key, value in page.context["form"].initial.items()
            if value is not None and not isinstance(value, list)
        }
        data.update(reference_form="consilium capere", schema="capio -obj-> {decisio}")
        page = self.client.post(url, data)
        self.assertContains(page, "Mot abstrait inconnu : {decisio}.")
        make_abstract_word(self.author, "decisio", [{"lemmas": ["consilium"]}])
        page = self.client.post(url, data)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.schema, "capio -obj-> {decisio}")

    def test_the_schema_search_takes_an_abstract_word(self):
        make_abstract_word(self.author)
        page = self.client.get(
            reverse("phraseology:schema_search"), {"schema": "sumo -obj-> {liquide}"}
        )
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Mot abstrait inconnu")
        page = self.client.get(
            reverse("phraseology:schema_search"), {"schema": "sumo -obj-> {ignotum}"}
        )
        self.assertContains(page, "Mot abstrait inconnu : {ignotum}.")


class AbstractWordChangesTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.word = make_abstract_word(self.author, "decisio", [{"lemmas": ["consilium"]}])
        self.unit.schema = "capio -obj-> {decisio}"
        update_unit(self.unit, self.author)
        refresh_frequency(self.unit)

    def test_a_change_of_its_rules_makes_the_frequency_no_longer_current(self):
        self.assertEqual(current_frequency(self.unit).total, 3)
        forms = UnitForm.objects.filter(unit=self.unit, lemma="{decisio}")
        self.assertFalse(forms.filter(norm="ratio").exists())
        self.word.rules = [{"upos": [], "feats": [], "lemmas": ["consilium", "ratio"]}]
        update_abstract_word(self.word, self.other)
        self.assertIsNone(current_frequency(self.unit))
        self.assertTrue(forms.filter(norm="ratio").exists())
        self.client.force_login(self.author)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertFalse(page.context["frequency_is_current"])
        refresh_frequency(self.unit)
        self.assertEqual(current_frequency(self.unit).total, 3)
        # A new label changes nothing that is counted.
        self.word.label = "décision"
        update_abstract_word(self.word, self.other)
        self.assertIsNotNone(current_frequency(self.unit))

    def test_a_validated_unit_uses_validated_abstract_words(self):
        self.assertIn("des mots abstraits validés", [str(f) for f in missing_fields(self.unit)])
        validate_abstract_word(self.word, self.reviewer)
        self.assertNotIn("des mots abstraits validés", [str(f) for f in missing_fields(self.unit)])
        make_abstract_word(self.author, "nomen", [{"upos": ["NOUN"]}])
        set_status(self.unit, Unit.Status.VALIDATED)
        self.unit.schema = "capio -obj-> {nomen}"
        with self.assertRaises(ValidationError):
            update_unit(self.unit, self.author)
