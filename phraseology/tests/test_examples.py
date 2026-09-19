from dataclasses import replace
from io import StringIO
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from corpus.models import Work
from corpus.text import normalize
from justifications.models import BibliographicWork
from moderation.models import Comment, Revision
from moderation.registry import can_view
from phraseology.abstract import clean_rules
from phraseology.examples import (
    EXAMPLE_ABSTRACTS,
    EXAMPLE_AUTHOR,
    EXAMPLE_REVIEWER,
    EXAMPLES,
    Example,
    ExamplesInUse,
    attestation_counts,
    create_example,
    create_example_abstracts,
    delete_examples,
    example_accounts,
    example_units,
)
from phraseology.models import (
    AbstractWord,
    Attestation,
    Candidate,
    Kind,
    Realization,
    Unit,
    UnitRelation,
    UsageMark,
)
from phraseology.schema import parse_schema, schema_abstracts
from phraseology.services import add_attestations, contest_unit, current_frequency, save_part
from translations.models import Language

from .factories import evidence
from .test_frequency import AnalysedCorpusTestCase

CONSILIUM = Example(
    "consilium capere",
    Kind.VERB_NOUN,
    "prendre une décision",
    (("fr", "prendre une décision"), ("en", "to make a decision")),
    schema="capio -obj|nsubj:pass-> consilium",
    construction="consilium capere + infinitif",
    realizations=(("consilium capere", Realization.Variation.BASE),),
    reference=("Gaffiot", "s. v. consilium"),
)
UT_ABIRET = Example(
    "ut abiret",
    Kind.FORMULA,
    "pour s’en aller",
    words=("ut", "abiret"),
    status=Unit.Status.PROPOSED,
)


class ExampleDataTests(TestCase):
    def test_the_examples_are_well_formed(self):
        abbreviations = set(BibliographicWork.objects.values_list("abbreviation", flat=True))
        for example in EXAMPLES:
            with self.subTest(example.reference_form):
                self.assertNotEqual(bool(example.schema), bool(example.words))
                if example.schema:
                    parse_schema(example.schema)
                self.assertEqual(example.words, tuple(normalize(word) for word in example.words))
                self.assertIn(example.kind, Kind.values)
                self.assertIn(example.register, Work.Register.values)
                self.assertIn(example.status, Unit.Status.values)
                for language, _expression in example.equivalents:
                    self.assertIn(language, Language.values)
                for _form, variation in example.realizations:
                    self.assertIn(variation, Realization.Variation.values)
                for mark in example.usage_marks:
                    self.assertIn(mark, UsageMark.values)
                if example.reference:
                    self.assertIn(example.reference[0], abbreviations)
                if example.status == Unit.Status.VALIDATED:
                    self.assertTrue(example.schema and example.construction)
                    self.assertTrue(example.equivalents and example.reference)
                if example.schema:
                    names = {name for name, *_rest in EXAMPLE_ABSTRACTS}
                    self.assertLessEqual(set(schema_abstracts(parse_schema(example.schema))), names)
        for _name, _label, _definition, rules in EXAMPLE_ABSTRACTS:
            self.assertEqual(clean_rules(rules), rules)


class ExampleTestCase(AnalysedCorpusTestCase):
    """Consilium capere in De officiis 1, 1 to 1, 3 and outside the core; ut abiret in 1, 1."""

    def setUp(self):
        super().setUp()
        self.focus = self.passage.edition.work
        self.example_author, self.example_reviewer = example_accounts()

    def create(self, example):
        return create_example(
            example, self.focus, self.layer, self.example_author, self.example_reviewer
        )


class CreationTests(ExampleTestCase):
    def test_a_validated_example_has_attestations_of_every_status(self):
        unit = self.create(CONSILIUM)
        self.assertEqual(unit.status, Unit.Status.VALIDATED)
        self.assertEqual(unit.created_by.email, EXAMPLE_AUTHOR)
        self.assertEqual(unit.validated_by.email, EXAMPLE_REVIEWER)
        self.assertEqual(current_frequency(unit).total, 4)
        self.assertEqual(attestation_counts(unit), {"validated": 1, "proposed": 1, "automatic": 2})
        example = unit.attestations.get(is_example=True)
        self.assertEqual(list(example.tokens.order_by("position")), list(self.words[:2]))
        self.assertEqual(example.status, Attestation.Status.VALIDATED)
        proposed = unit.attestations.get(level=Attestation.Level.VALIDATED, status="proposed")
        self.assertEqual(proposed.passage, self.second_passage)
        outside = unit.attestations.get(passage__edition__work__is_core=False)
        self.assertEqual(outside.level, Attestation.Level.AUTOMATIC)
        self.assertEqual(unit.senses.get().equivalents.count(), 2)
        self.assertEqual(unit.references.get().locator, "s. v. consilium")
        self.assertEqual(unit.realizations.get().form, "consilium capere")

    def test_a_unit_without_schema_is_found_by_its_words(self):
        unit = self.create(UT_ABIRET)
        self.assertEqual(unit.status, Unit.Status.PROPOSED)
        attestation = unit.attestations.get()
        self.assertEqual(list(attestation.tokens.order_by("position")), list(self.words[2:4]))
        self.assertTrue(attestation.is_example)
        self.assertEqual(attestation.status, Attestation.Status.VALIDATED)

    def test_a_draft_stays_with_the_example_account(self):
        unit = self.create(replace(CONSILIUM, status=Unit.Status.DRAFT))
        self.assertEqual(unit.status, Unit.Status.DRAFT)
        self.assertFalse(unit.attestations.filter(status=Attestation.Status.VALIDATED).exists())
        self.assertFalse(can_view(self.other, unit))

    def test_an_example_the_corpus_lacks_is_not_created(self):
        self.assertIsNone(self.create(replace(UT_ABIRET, words=("ut", "maneret"))))
        self.assertFalse(example_units().exists())

    def test_the_accounts_are_made_once_and_cannot_log_in(self):
        self.assertEqual(example_accounts(), [self.example_author, self.example_reviewer])
        self.assertFalse(self.example_author.has_usable_password())
        self.assertTrue(self.example_author.is_confirmed)


class DeletionTests(ExampleTestCase):
    def setUp(self):
        super().setUp()
        self.example = self.create(CONSILIUM)
        self.create(UT_ABIRET)

    def test_the_examples_and_what_was_added_to_them_are_deleted(self):
        example_id = self.example.pk
        add_attestations(self.example, [evidence(*self.good_words)], self.other)
        contest_unit(self.example, self.other, "Ce n’est pas une collocation.")
        now = timezone.now()
        candidate = Candidate.objects.create(
            head="capio",
            relation="obj",
            dependent="consilium",
            frequency=3,
            score=12.0,
            layer=self.layer,
            corpus_version="test",
            extracted_at=now,
            status=Candidate.Status.RETAINED,
            unit=self.example,
            decided_by=self.other,
            decided_at=now,
        )
        counts = delete_examples()
        self.assertEqual(counts["units"], 2)
        self.assertEqual(counts["attestations"], 6)
        self.assertEqual(counts["candidates"], 1)
        self.assertEqual(counts["accounts"], 2)
        self.assertFalse(example_units().exists())
        self.assertFalse(User.objects.filter(email__in=(EXAMPLE_AUTHOR, EXAMPLE_REVIEWER)).exists())
        unit_type = ContentType.objects.get_for_model(Unit)
        self.assertFalse(Revision.objects.filter(content_type=unit_type, object_id=example_id))
        self.assertFalse(Comment.objects.exists())
        candidate.refresh_from_db()
        self.assertEqual((candidate.status, candidate.unit), (Candidate.Status.PENDING, None))
        self.assertTrue(Revision.objects.filter(content_type=unit_type, object_id=self.unit.pk))
        self.assertEqual(Attestation.objects.filter(unit=self.unit).count(), 1)

    def test_the_abstract_words_of_the_examples(self):
        create_example_abstracts(self.example_author, self.example_reviewer)
        create_example_abstracts(self.example_author, self.example_reviewer)
        word = AbstractWord.objects.get(name="liquide")
        self.assertEqual(word.status, AbstractWord.Status.VALIDATED)
        Unit.objects.filter(pk=self.unit.pk).update(schema="capio -obj-> {liquide}")
        with self.assertRaises(ExamplesInUse) as caught:
            delete_examples()
        self.assertEqual(caught.exception.links, {"abstract_words": 1})
        Unit.objects.filter(pk=self.unit.pk).update(schema="")
        self.assertEqual(delete_examples()["abstract_words"], len(EXAMPLE_ABSTRACTS))
        self.assertFalse(AbstractWord.objects.exists())

    def test_a_link_from_another_content_stops_the_deletion(self):
        relation = UnitRelation(unit=self.unit, target=self.example, kind=UnitRelation.Kind.SYNONYM)
        save_part(relation, self.author)
        with self.assertRaises(ExamplesInUse) as caught:
            delete_examples()
        self.assertEqual(caught.exception.links, {"relations": 1})
        self.assertEqual(example_units().count(), 2)


class CommandTests(ExampleTestCase):
    def call(self, name):
        output = StringIO()
        with mock.patch(
            "phraseology.management.commands.create_examples.EXAMPLES", (CONSILIUM, UT_ABIRET)
        ):
            call_command(name, stdout=output)
        return output.getvalue()

    def test_the_commands_run_on_a_development_machine_only(self):
        for name in ("create_examples", "delete_examples"):
            with self.assertRaises(CommandError):
                self.call(name)
        self.assertFalse(example_units().exists())

    @override_settings(DEBUG=True)
    def test_create_then_delete(self):
        output = self.call("create_examples")
        self.assertIn(
            "consilium capere (validée) : attestations validées 1, proposées 1, "
            "repérées automatiquement 2.",
            output,
        )
        self.assertIn("2 fiches d’exemple créées.", output)
        with self.assertRaises(CommandError):
            self.call("create_examples")
        output = self.call("delete_examples")
        self.assertIn("fiches d’exemple 2, attestations 5", output)
        self.assertFalse(example_units().exists())
