from django.core.exceptions import PermissionDenied, ValidationError

from moderation.models import Comment
from phraseology.models import Attestation, Equivalent, Unit, UnitReference
from phraseology.services import (
    contest_unit,
    missing_fields,
    propose_unit,
    resolve_contest,
    review_attestation,
    save_part,
    set_example,
    update_unit,
    validate_unit,
    withdraw_part,
)

from .test_frequency import AnalysedCorpusTestCase


class ValidationTestCase(AnalysedCorpusTestCase):
    def complete(self, unit):
        """Fill every field a validation demands; a draft is proposed first, for the reviewer."""
        if unit.is_draft:
            propose_unit(unit, self.author)
            unit.refresh_from_db()
        unit.kind = "verb-noun"
        unit.schema = "capio -obj-> consilium"
        unit.construction = "+ infinitif"
        unit.register = "standard"
        update_unit(unit, self.author)
        self.equivalent = Equivalent(
            sense=unit.senses.get(), language="fr", expression="prendre une décision"
        )
        save_part(self.equivalent, self.author)
        save_part(UnitReference(unit=unit, work=self.grammar, locator="§ 563"), self.author)
        self.example = unit.attestations.get()
        review_attestation(self.example, self.reviewer, Attestation.Status.VALIDATED)
        self.example.refresh_from_db()
        set_example(self.example, self.author, True)
        return unit

    def validated(self):
        propose_unit(self.unit, self.author)
        self.complete(self.unit)
        validate_unit(self.unit, self.reviewer)
        self.unit.refresh_from_db()
        return self.unit


class ProposalTests(ValidationTestCase):
    def test_only_the_creator_proposes_a_draft(self):
        with self.assertRaises(PermissionDenied):
            propose_unit(self.unit, self.other)
        revision = propose_unit(self.unit, self.author)
        self.assertEqual(revision.comment, "Proposition")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.PROPOSED)
        self.assertIsNone(propose_unit(self.unit, self.author))


class CompletenessTests(ValidationTestCase):
    def test_every_field_is_demanded(self):
        self.assertEqual(
            [str(field) for field in missing_fields(self.unit)],
            [
                "le type",
                "le schéma",
                "la construction",
                "le registre",
                "un équivalent pour chaque sens",
                "un exemple choisi parmi les attestations validées",
                "un renvoi bibliographique",
            ],
        )
        self.complete(self.unit)
        self.assertEqual(missing_fields(self.unit), [])

    def test_validation_by_a_reviewer_of_a_complete_unit(self):
        propose_unit(self.unit, self.author)
        with self.assertRaises(ValidationError) as caught:
            validate_unit(self.unit, self.reviewer)
        self.assertIn("le type", caught.exception.messages[0])
        self.complete(self.unit)
        with self.assertRaises(PermissionDenied):
            validate_unit(self.unit, self.other)
        revision = validate_unit(self.unit, self.reviewer)
        self.assertEqual(revision.comment, "Validation")
        self.unit.refresh_from_db()
        self.assertEqual(
            (self.unit.status, self.unit.validated_by), (Unit.Status.VALIDATED, self.reviewer)
        )

    def test_a_draft_is_not_validated(self):
        with self.assertRaises(ValidationError) as caught:
            validate_unit(self.unit, self.reviewer)
        self.assertEqual(caught.exception.code, "not_proposed")

    def test_a_validated_unit_stays_complete(self):
        unit = self.validated()
        unit.construction = ""
        with self.assertRaises(ValidationError):
            update_unit(unit, self.other)
        unit.refresh_from_db()
        self.assertEqual(unit.construction, "+ infinitif")
        with self.assertRaises(ValidationError):
            withdraw_part(self.equivalent, self.other)
        with self.assertRaises(ValidationError):
            review_attestation(self.example, self.reviewer, Attestation.Status.REJECTED)
        unit.construction = "+ infinitif ou ut"
        update_unit(unit, self.other)
        unit.refresh_from_db()
        self.assertEqual(unit.status, Unit.Status.VALIDATED)


class AttestationReviewTests(ValidationTestCase):
    def test_a_checked_attestation_is_no_longer_automatic(self):
        attestation = self.unit.attestations.get()
        Attestation.objects.filter(pk=attestation.pk).update(level=Attestation.Level.AUTOMATIC)
        with self.assertRaises(PermissionDenied):
            review_attestation(attestation, self.author, Attestation.Status.VALIDATED)
        propose_unit(self.unit, self.author)
        review_attestation(attestation, self.reviewer, Attestation.Status.VALIDATED)
        attestation.refresh_from_db()
        self.assertEqual(
            (attestation.level, attestation.status, attestation.reviewed_by),
            (Attestation.Level.VALIDATED, Attestation.Status.VALIDATED, self.reviewer),
        )

    def test_a_rejected_attestation_is_no_example(self):
        propose_unit(self.unit, self.author)
        attestation = self.unit.attestations.get()
        set_example(attestation, self.author, True)
        review_attestation(attestation, self.reviewer, Attestation.Status.REJECTED)
        attestation.refresh_from_db()
        self.assertFalse(attestation.is_example)
        with self.assertRaises(ValidationError):
            set_example(attestation, self.author, True)


class ContestTests(ValidationTestCase):
    def test_contest_and_resolution(self):
        unit = self.validated()
        contest_unit(unit, self.other, "Ce n’est pas une collocation.")
        unit.refresh_from_db()
        self.assertEqual(unit.status, Unit.Status.CONTESTED)
        self.assertEqual(Comment.objects.for_object(unit).get().author, self.other)
        with self.assertRaises(ValidationError):
            contest_unit(unit, self.other, "Encore.")
        with self.assertRaises(PermissionDenied):
            resolve_contest(unit, self.other, Unit.Status.VALIDATED, "Non.")
        resolve_contest(unit, self.reviewer, Unit.Status.PROPOSED, "À revoir.")
        unit.refresh_from_db()
        self.assertEqual(unit.status, Unit.Status.PROPOSED)
        self.assertEqual(Comment.objects.for_object(unit).count(), 2)
        contest_unit(unit, self.other, "Toujours pas.")
        resolve_contest(unit, self.reviewer, Unit.Status.VALIDATED, "Défendable.")
        unit.refresh_from_db()
        self.assertEqual(unit.status, Unit.Status.VALIDATED)

    def test_a_draft_is_not_contested(self):
        with self.assertRaises(ValidationError):
            contest_unit(self.unit, self.author, "Brouillon.")
