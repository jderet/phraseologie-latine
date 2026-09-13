from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from justifications.models import BibliographicWork, Evidence, Justification, Strength
from justifications.services import (
    add_evidences,
    corpus_evidence,
    create_justification,
    reference_evidence,
    update_justification,
    withdraw_evidence,
)
from moderation.models import Revision
from moderation.registry import uncounted_models
from moderation.services import revert_to
from translations.services import save_translation
from translations.tests.factories import make_version, translate
from translations.tests.test_versions import TranslationTestCase

from .factories import make_passage


class JustificationTestCase(TranslationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.passage, cls.words = make_passage(("Domi", "manemus", "hodie."))
        cls.grammar = BibliographicWork.objects.get(abbreviation="A&G")

    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version)
        self.translated = self.version.segments.get(segment=self.second)

    def attestation(self, *words):
        words = words or self.words[:2]
        return corpus_evidence(",".join(str(word.pk) for word in words))

    def justify(self, strength=Strength.ATTESTED, excerpt="manemus", evidences=None, **fields):
        if evidences is None:
            evidences = [self.attestation()]
        user = fields.pop("user", self.author)
        hint = fields.pop("hint", None)
        justification = Justification(
            translated_segment=self.translated, latin_excerpt=excerpt, strength=strength, **fields
        )
        return create_justification(justification, user, evidences, hint)

    def fresh(self, justification):
        return Justification.objects.select_related("translated_segment").get(pk=justification.pk)


class CreationTests(JustificationTestCase):
    def test_justification_with_an_attestation(self):
        justification = self.justify()
        self.assertEqual(justification.locate(), (5, 12))
        evidence = justification.evidences.get()
        self.assertEqual((evidence.kind, evidence.passage), (Evidence.Kind.CORPUS, self.passage))
        self.assertEqual(list(evidence.tokens.order_by("position")), self.words[:2])
        revision = Revision.objects.for_object(evidence).get()
        self.assertCountEqual(revision.after["tokens"], [word.pk for word in self.words[:2]])
        self.assertIn(Evidence, uncounted_models())
        self.assertNotIn(Justification, uncounted_models())

    def test_the_excerpt_must_be_in_the_latin(self):
        with self.assertRaises(ValidationError):
            self.justify(excerpt="manebimus")

    def test_the_occurrence_nearest_the_selection(self):
        save_translation(self.version, self.second, "domi manemus et domi dormimus.", self.author)
        self.translated.refresh_from_db()
        self.assertEqual(self.justify(excerpt="domi", hint=15).latin_start, 16)
        self.assertEqual(self.justify(excerpt="domi").latin_start, 0)

    def test_evidence_required_by_each_strength(self):
        reference = reference_evidence(self.grammar, "§ 426")
        for strength in (Strength.ATTESTED, Strength.VARIANT, Strength.MARGINAL):
            with self.subTest(strength=strength), self.assertRaises(ValidationError):
                self.justify(strength=strength, evidences=[reference])
        with self.assertRaises(ValidationError):
            self.justify(strength=Strength.ANALOGY, evidences=[reference])
        with self.assertRaises(ValidationError):
            self.justify(strength=Strength.ANALOGY, comment="Comme domi esse.", evidences=[])
        analogy = self.justify(
            strength=Strength.ANALOGY, comment="Comme domi esse.", evidences=[reference]
        )
        self.assertEqual(analogy.evidences.get().work, self.grammar)
        with self.assertRaises(ValidationError):
            self.justify(strength=Strength.NOT_FOUND, evidences=[])
        not_found = self.justify(strength=Strength.NOT_FOUND, comment="Rien trouvé.", evidences=[])
        self.assertTrue(not_found.corpus_version.startswith("Perseus"))

    def test_the_database_requires_a_comment_for_an_analogy(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Justification.objects.create(
                translated_segment=self.translated,
                author=self.author,
                latin_excerpt="Domi",
                strength=Strength.ANALOGY,
            )

    def test_only_the_author_of_the_version_justifies(self):
        with self.assertRaises(PermissionDenied):
            self.justify(user=self.other)

    def test_invalid_attestations(self):
        too_many = ",".join(str(number) for number in range(1, 20))
        for value in ("", "abc", "999999999", too_many):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                corpus_evidence(value)


class ReviewTests(JustificationTestCase):
    def test_changed_latin_is_to_be_reviewed(self):
        justification = self.justify()
        save_translation(self.version, self.second, "Hodie domi manemus.", self.author)
        moved = self.fresh(justification)
        self.assertEqual((moved.needs_review, moved.locate()), (False, (11, 18)))

        save_translation(self.version, self.second, "Domi manebimus.", self.author)
        changed = self.fresh(justification)
        self.assertTrue(changed.needs_review)
        changed.latin_excerpt = "manebimus"
        with self.assertRaises(PermissionDenied):
            update_justification(changed, self.other)
        update_justification(changed, self.author)
        self.assertFalse(self.fresh(justification).needs_review)

    def test_a_revert_of_the_latin_is_followed(self):
        justification = self.justify()
        first = Revision.objects.for_object(self.translated).order_by("created_at", "pk").first()
        save_translation(self.version, self.second, "Domi manebimus.", self.author)
        self.assertTrue(self.fresh(justification).needs_review)
        revert_to(first, self.author)
        self.assertFalse(self.fresh(justification).needs_review)

    def test_withdrawn_evidence_leaves_what_the_strength_needs(self):
        justification = self.justify()
        evidence = justification.evidences.get()
        with self.assertRaises(ValidationError):
            withdraw_evidence(evidence, self.author)
        (added,) = add_evidences(justification, [self.attestation(self.words[2])], self.author)
        with self.assertRaises(PermissionDenied):
            withdraw_evidence(added, self.other)
        withdraw_evidence(evidence, self.author)
        evidence.refresh_from_db()
        self.assertTrue(evidence.is_withdrawn)

    def test_the_corpus_version_follows_the_strength(self):
        justification = self.justify()
        justification.strength = Strength.NOT_FOUND
        update_justification(justification, self.author)
        self.assertTrue(self.fresh(justification).corpus_version)
        justification.strength = Strength.VARIANT
        update_justification(justification, self.author)
        self.assertEqual(self.fresh(justification).corpus_version, "")
