from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from accounts.roles import CONTRIBUTOR, REVIEWER
from accounts.tests.factories import make_user
from justifications.models import BibliographicWork
from justifications.tests.factories import make_passage
from moderation.models import Revision
from moderation.registry import can_view, uncounted_models
from moderation.services import revert_to, save_with_revision
from phraseology.models import (
    Attestation,
    Equivalent,
    Realization,
    Sense,
    Unit,
    UnitReference,
    UnitRelation,
)
from phraseology.permissions import can_edit_unit
from phraseology.services import (
    add_attestations,
    create_unit,
    save_part,
    update_unit,
    withdraw_attestation,
    withdraw_part,
)

from .factories import evidence, make_unit, set_status


class PhraseologyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = make_user(
            email="author@example.org", display_name="Marcus", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.other = make_user(
            email="other@example.org", display_name="Quintus", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.reviewer = make_user(email="reviewer@example.org", display_name="Titus", role=REVIEWER)
        cls.passage, cls.words = make_passage(("Consilium", "cepit", "ut", "abiret."))
        cls.second_passage, cls.more_words = make_passage(
            ("Consilia", "capiunt", "celeriter."), reference="1.2"
        )
        cls.grammar = BibliographicWork.objects.get(abbreviation="A&G")

    def setUp(self):
        self.unit = make_unit(self.author, self.words[:2])


class CreationTests(PhraseologyTestCase):
    def test_three_fields_make_a_draft(self):
        unit = self.unit
        self.assertEqual(unit.status, Unit.Status.DRAFT)
        self.assertEqual(unit.created_by, self.author)
        self.assertEqual(unit.senses.get().definition, "prendre une décision")
        attestation = unit.attestations.get()
        self.assertEqual(list(attestation.tokens.order_by("position")), self.words[:2])
        self.assertEqual(attestation.passage, self.passage)
        self.assertEqual(attestation.status, Attestation.Status.PROPOSED)
        self.assertEqual(attestation.level, Attestation.Level.VALIDATED)
        self.assertEqual(attestation.status_label, "proposée")
        self.assertEqual(Revision.objects.filter(author=self.author).count(), 3)

    def test_the_sense_and_the_attestation_are_required(self):
        with self.assertRaises(ValidationError):
            create_unit(
                Unit(reference_form="bellum gerere"), self.author, " ", [evidence(*self.words)]
            )
        with self.assertRaises(ValidationError):
            create_unit(Unit(reference_form="bellum gerere"), self.author, "faire la guerre", [])
        self.assertEqual(Unit.objects.count(), 1)

    def test_only_the_unit_counts_toward_the_limit_of_new_accounts(self):
        for model in (Sense, Equivalent, Realization, UnitRelation, UnitReference, Attestation):
            self.assertIn(model, uncounted_models())
        self.assertNotIn(Unit, uncounted_models())

    def test_an_automatic_attestation_is_never_shown_as_validated(self):
        attestation = self.unit.attestations.get()
        attestation.level = Attestation.Level.AUTOMATIC
        self.assertEqual(attestation.status_label, "repérée automatiquement")


class EditingRightsTests(PhraseologyTestCase):
    def test_a_draft_is_seen_and_edited_by_its_creator_only(self):
        self.assertTrue(can_view(self.author, self.unit))
        self.assertTrue(can_edit_unit(self.author, self.unit))
        for user in (self.other, self.reviewer):
            self.assertFalse(can_view(user, self.unit))
            self.assertFalse(can_edit_unit(user, self.unit))
        sense = self.unit.senses.get()
        self.assertFalse(can_view(self.other, sense))
        with self.assertRaises(PermissionDenied):
            update_unit(self.unit, self.other)

    def test_a_proposed_unit_is_completed_by_any_active_account(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        self.assertTrue(can_edit_unit(self.other, self.unit))
        self.unit.construction = "consilium capere + infinitif"
        revision = update_unit(self.unit, self.other)
        self.assertEqual(revision.author, self.other)
        self.other.is_active = False
        self.assertFalse(can_edit_unit(self.other, self.unit))

    def test_a_hidden_unit_is_edited_by_reviewers_only(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        Unit.objects.filter(pk=self.unit.pk).update(is_hidden=True)
        self.unit.refresh_from_db()
        self.assertFalse(can_edit_unit(self.author, self.unit))
        self.assertTrue(can_edit_unit(self.reviewer, self.unit))

    def test_a_revert_does_not_change_the_status(self):
        self.unit.construction = "+ infinitif"
        update_unit(self.unit, self.author)
        first = Revision.objects.for_object(self.unit).order_by("created_at").first()
        set_status(self.unit, Unit.Status.PROPOSED)
        revert_to(first, self.author)
        self.unit.refresh_from_db()
        self.assertEqual((self.unit.construction, self.unit.status), ("", Unit.Status.PROPOSED))


class PartsTests(PhraseologyTestCase):
    def test_senses_equivalents_realizations_and_references(self):
        sense = self.unit.senses.get()
        save_part(
            Equivalent(sense=sense, language="fr", expression="prendre une décision"), self.author
        )
        save_part(
            Realization(unit=self.unit, form="consilium capitur", variation="passive"), self.author
        )
        save_part(UnitReference(unit=self.unit, work=self.grammar, locator="§ 563"), self.author)
        self.assertEqual(sense.equivalents.get().unit, self.unit)
        self.assertEqual(self.unit.realizations.get().get_variation_display(), "passif")
        self.assertEqual(str(self.unit.references.get()), "A&G § 563")

    def test_a_unit_keeps_one_sense(self):
        sense = self.unit.senses.get()
        with self.assertRaises(ValidationError):
            withdraw_part(sense, self.author)
        other = Sense(unit=self.unit, definition="décider")
        save_part(other, self.author)
        revision = withdraw_part(sense, self.author)
        self.assertEqual(revision.comment, "Retrait")
        self.assertEqual(list(self.unit.senses.active()), [other])
        self.assertIsNone(withdraw_part(self.unit.senses.get(pk=sense.pk), self.author))

    def test_relations_link_two_public_units(self):
        target = make_unit(self.author, self.more_words[:2], reference_form="consilia inire")
        relation = UnitRelation(unit=self.unit, target=target, kind=UnitRelation.Kind.BROADER)
        with self.assertRaises(ValidationError):
            save_part(relation, self.author)
        set_status(target, Unit.Status.PROPOSED)
        save_part(relation, self.author)
        self.assertEqual(relation.inverse_label, "plus précis que")
        with self.assertRaises(ValidationError):
            save_part(UnitRelation(unit=self.unit, target=self.unit, kind="synonym"), self.author)

    def test_parts_of_a_draft_are_written_by_its_creator(self):
        with self.assertRaises(PermissionDenied):
            save_part(Sense(unit=self.unit, definition="décider"), self.other)


class AttestationTests(PhraseologyTestCase):
    def test_words_already_attested_are_skipped(self):
        created = add_attestations(
            self.unit, [evidence(*self.words[:2]), evidence(*self.more_words[:2])], self.author
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(self.unit.attestations.count(), 2)

    def test_withdrawal(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        first = self.unit.attestations.get()
        with self.assertRaises(ValidationError):
            withdraw_attestation(first, self.author)
        (second,) = add_attestations(self.unit, [evidence(*self.more_words[:2])], self.other)
        with self.assertRaises(PermissionDenied):
            withdraw_attestation(second, self.author)
        withdraw_attestation(second, self.other)
        self.assertEqual(list(self.unit.attestations.active()), [first])

    def test_a_validated_attestation_is_withdrawn_by_a_reviewer_only(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        add_attestations(self.unit, [evidence(*self.more_words[:2])], self.author)
        attestation = self.unit.attestations.first()
        attestation.status = Attestation.Status.VALIDATED
        save_with_revision(attestation, self.reviewer)
        with self.assertRaises(PermissionDenied):
            withdraw_attestation(attestation, self.author)
        withdraw_attestation(attestation, self.reviewer)
