from django.core.exceptions import PermissionDenied, ValidationError

from translations import members
from translations.models import (
    ProjectMember,
    SegmentVariant,
    TranslatedSegment,
)
from translations.services import save_translation
from translations.variants import (
    add_variant,
    adopt_variant,
    can_add_variant,
    can_decide_variant,
    delete_variant,
    edit_variant,
    refuse_variant,
    variants_for,
)

from .factories import make_published_version
from .test_versions import TranslationTestCase


class VariantTestCase(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)

    def add(self, user=None, text="Imber cadit.", **fields):
        fields.setdefault("segment", self.first)
        fields.setdefault("comment", "Plus proche de Cicéron.")
        return add_variant(
            SegmentVariant(version=self.version, text=text, **fields), user or self.other
        )

    def main_text(self, segment=None):
        return TranslatedSegment.objects.get(
            version=self.version, segment=segment or self.first
        ).text


class VariantServicesTests(VariantTestCase):
    def test_anyone_adds_a_variant_while_the_correction_is_open(self):
        variant = self.add()
        self.assertEqual((variant.author, variant.segment), (self.other, self.first))
        self.assertTrue(variant.is_proposal)
        self.assertTrue(variant.is_pending)
        self.assertIsNone(variant.target)
        self.assertEqual(
            [item.pk for item in variants_for(self.other, self.version, self.first)], [variant.pk]
        )

    def test_a_closed_correction_keeps_the_named_members_only(self):
        self.project.open_correction = False
        self.project.save(update_fields=["open_correction"])
        self.version.project = self.project
        self.assertFalse(can_add_variant(self.other, self.version))
        with self.assertRaises(PermissionDenied):
            self.add()
        member = members.invite(self.project, self.author, self.other, ProjectMember.Role.CORRECTOR)
        members.answer(member, self.other, accept=True)
        self.version.project.__dict__.pop("_role_ids", None)
        self.assertTrue(can_add_variant(self.other, self.version))

    def test_a_variant_says_something_else_than_what_it_corrects(self):
        with self.assertRaises(ValidationError) as caught:
            self.add(text="Pluit.")
        self.assertEqual(caught.exception.code, "same")
        with self.assertRaises(ValidationError):
            self.add(text="   ")

    def test_a_variant_may_correct_another_variant(self):
        first = self.add()
        second = self.add(user=self.reviewer, text="Imber ruit.", target=first)
        self.assertEqual(second.target, first)
        # Both are shown under the sentence.
        self.assertEqual(len(variants_for(self.author, self.version, self.first)), 2)

    def test_a_variant_of_another_sentence_is_refused(self):
        first = self.add()
        with self.assertRaises(ValidationError) as caught:
            self.add(text="Domi sumus.", segment=self.second, target=first)
        self.assertEqual(caught.exception.code, "other_sentence")

    def test_adopting_a_proposal_writes_the_main_text_and_keeps_the_old_one(self):
        variant = self.add()
        self.assertTrue(can_decide_variant(self.author, variant))
        self.assertFalse(can_decide_variant(self.other, variant))
        adopt_variant(variant, self.author)
        variant.refresh_from_db()
        self.assertEqual(self.main_text(), "Imber cadit.")
        translated = TranslatedSegment.objects.get(version=self.version, segment=self.first)
        self.assertEqual(translated.written_by, self.other)
        self.assertTrue(variant.is_adopted)
        [kept] = [
            item
            for item in variants_for(self.author, self.version, self.first)
            if item.pk != variant.pk
        ]
        self.assertEqual((kept.text, kept.status), ("Pluit.", SegmentVariant.Status.REFERENCE))
        self.assertEqual(kept.author, self.author)

    def test_a_proposal_is_decided_once(self):
        variant = self.add()
        adopt_variant(variant, self.author)
        variant.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            refuse_variant(variant, self.author)

    def test_adopting_moves_the_corrections_to_the_main_text(self):
        first = self.add()
        second = self.add(user=self.reviewer, text="Imber ruit.", target=first)
        adopt_variant(first, self.author)
        second.refresh_from_db()
        self.assertIsNone(second.target)

    def test_adopting_a_correction_of_a_variant_keeps_it_for_reference(self):
        first = self.add()
        second = self.add(user=self.reviewer, text="Imber ruit.", target=first)
        adopt_variant(second, self.author)
        first.refresh_from_db()
        self.assertEqual(self.main_text(), "Imber ruit.")
        self.assertEqual(first.status, SegmentVariant.Status.REFERENCE)

    def test_a_refused_proposal_is_kept_for_reference(self):
        variant = self.add()
        refuse_variant(variant, self.author)
        variant.refresh_from_db()
        self.assertEqual(variant.status, SegmentVariant.Status.REFERENCE)
        self.assertEqual(variant.decision, SegmentVariant.Decision.REFUSED)
        self.assertEqual(variant.decided_by, self.author)
        self.assertEqual(self.main_text(), "Pluit.")

    def test_a_variant_kept_for_reference_is_never_decided(self):
        variant = self.add(status=SegmentVariant.Status.REFERENCE)
        self.assertFalse(variant.is_pending)
        self.assertFalse(can_decide_variant(self.author, variant))
        with self.assertRaises(PermissionDenied):
            adopt_variant(variant, self.author)

    def test_its_author_rewrites_it_until_it_is_decided(self):
        variant = self.add()
        edit_variant(variant, self.other, "Imber magnus.", "Mieux.", variant.status)
        variant.refresh_from_db()
        self.assertEqual((variant.text, variant.comment), ("Imber magnus.", "Mieux."))
        refuse_variant(variant, self.author)
        variant.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            edit_variant(variant, self.other, "Encore.", "", variant.status)
        # A translator may still rewrite it.
        edit_variant(variant, self.author, "Imber ingens.", "", variant.status)

    def test_a_deleted_variant_leaves_its_corrections_in_place(self):
        first = self.add()
        second = self.add(user=self.reviewer, text="Imber ruit.", target=first)
        with self.assertRaises(PermissionDenied):
            delete_variant(first, self.reviewer)
        delete_variant(first, self.other)
        second.refresh_from_db()
        self.assertIsNone(second.target)
        self.assertFalse(SegmentVariant.objects.filter(pk=first.pk).exists())

    def test_a_variant_of_a_sentence_without_latin(self):
        save_translation(self.version, self.first, "", self.author)
        variant = self.add(text="Imber cadit.")
        adopt_variant(variant, self.author)
        self.assertEqual(self.main_text(), "Imber cadit.")
        self.assertEqual(len(variants_for(self.author, self.version, self.first)), 1)
