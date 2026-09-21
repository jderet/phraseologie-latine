from django.urls import reverse

from translations.models import SegmentVariant
from translations.variants import add_variant

from .factories import make_published_version
from .test_versions import TranslationTestCase


class VariantPageTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        self.url = reverse(
            "translations:variant_create", args=[self.version.pk, self.first.pk]
        )

    def add(self, user=None, text="Imber cadit.", **fields):
        fields.setdefault("segment", self.first)
        return add_variant(
            SegmentVariant(version=self.version, text=text, comment="Mieux.", **fields),
            user or self.other,
        )

    def test_the_form_adds_a_variant_and_the_page_shows_it(self):
        self.client.force_login(self.other)
        response = self.client.post(
            self.url,
            {"text": "Imber cadit.", "status": "proposal", "comment": "Plus cicéronien."},
        )
        variant = SegmentVariant.objects.get()
        self.assertRedirects(response, variant.get_absolute_url())
        page = self.client.get(self.version.get_absolute_url())
        self.assertContains(page, "Imber cadit.")
        self.assertContains(page, "Plus cicéronien.")

    def test_a_visitor_never_adds_a_variant(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_a_closed_correction_closes_the_page(self):
        self.project.open_correction = False
        self.project.save(update_fields=["open_correction"])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_translator_adopts_from_the_page(self):
        variant = self.add()
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("translations:variant_decide", args=[variant.pk]), {"decision": "adopt"}
        )
        self.assertRedirects(
            response, variant.get_absolute_url(), fetch_redirect_response=False
        )
        page = self.client.get(self.version.get_absolute_url())
        self.assertContains(page, "Imber cadit.")
        self.assertContains(page, "Texte principal remplacé")

    def test_only_a_translator_decides_from_the_page(self):
        variant = self.add()
        self.client.force_login(self.reviewer)
        response = self.client.post(
            reverse("translations:variant_decide", args=[variant.pk]), {"decision": "refuse"}
        )
        self.assertEqual(response.status_code, 404)

    def test_its_author_rewrites_and_removes_it_from_the_page(self):
        variant = self.add()
        self.client.force_login(self.other)
        url = reverse("translations:variant_edit", args=[variant.pk])
        response = self.client.post(
            url, {"text": "Imber ruit.", "status": "reference", "comment": "Pour mémoire."}
        )
        self.assertRedirects(response, variant.get_absolute_url(), fetch_redirect_response=False)
        variant.refresh_from_db()
        self.assertEqual(variant.text, "Imber ruit.")
        self.client.post(reverse("translations:variant_delete", args=[variant.pk]))
        self.assertFalse(SegmentVariant.objects.exists())

    def test_the_editor_panel_lists_the_variants(self):
        self.add()
        self.client.force_login(self.author)
        page = self.client.get(
            reverse("translations:editor_variants", args=[self.version.pk, self.first.pk])
        )
        self.assertContains(page, "Imber cadit.")
        self.assertContains(page, "Adopter")

    def test_a_variant_corrects_another_from_the_page(self):
        first = self.add()
        self.client.force_login(self.reviewer)
        response = self.client.post(
            self.url,
            {
                "text": "Imber ruit.",
                "status": "proposal",
                "comment": "Encore mieux.",
                "corrige": str(first.pk),
            },
        )
        second = SegmentVariant.objects.get(text="Imber ruit.")
        self.assertEqual(second.target, first)
        self.assertRedirects(response, second.get_absolute_url(), fetch_redirect_response=False)
