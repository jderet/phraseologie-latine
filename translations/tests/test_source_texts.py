from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import CONTRIBUTOR, REVIEWER
from accounts.tests.factories import make_user
from moderation.models import Revision
from moderation.services import hide_content
from translations.models import License, Segment, SourceText, last_public_domain_death_year

from .factories import make_source_text


class SourceTextRulesTests(TestCase):
    def setUp(self):
        self.user = make_user(role=CONTRIBUTOR)

    def build(self, **fields):
        values = {
            "title": "Titre",
            "language": "fr",
            "license": License.CC_BY_SA_4,
            "source_url": "https://fr.wikipedia.org/wiki/Titre",
            "text": "Une phrase.",
            "added_by": self.user,
        }
        return SourceText(**(values | fields))

    def test_public_domain_needs_an_author_dead_for_seventy_years(self):
        last_year = timezone.localdate().year - 71
        self.assertEqual(last_public_domain_death_year(), last_year)
        self.build(license=License.PUBLIC_DOMAIN, author_death_year=last_year).full_clean()
        for year in (None, last_year + 1):
            with self.subTest(year=year), self.assertRaises(ValidationError) as caught:
                self.build(license=License.PUBLIC_DOMAIN, author_death_year=year).full_clean()
            self.assertIn("author_death_year", caught.exception.message_dict)

    def test_free_licenses_need_the_source_address(self):
        with self.assertRaises(ValidationError) as caught:
            self.build(source_url="").full_clean()
        self.assertIn("source_url", caught.exception.message_dict)

    def test_incompatible_licenses_are_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.build(license="cc-by-nc-4.0").full_clean()
        self.assertIn("license", caught.exception.message_dict)

    def test_the_database_enforces_the_rules(self):
        cases = [
            {"license": License.PUBLIC_DOMAIN, "author_death_year": None},
            {"source_url": ""},
        ]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    self.build(**fields).save()

    def test_creation_records_the_split_and_a_revision(self):
        source = make_source_text(self.user)
        self.assertEqual(
            list(source.segments.values_list("order", "text")),
            [(1, "Il pleut."), (2, "Nous restons à la maison."), (3, "Demain, nous partirons.")],
        )
        revision = Revision.objects.for_object(source).get()
        self.assertEqual(revision.action, Revision.Action.CREATE)
        self.assertEqual(revision.after["text"], source.text)


class SourceTextPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(email="owner@example.org", role=CONTRIBUTOR, is_confirmed=True)
        cls.other = make_user(email="other@example.org", role=CONTRIBUTOR, is_confirmed=True)
        cls.reviewer = make_user(email="reviewer@example.org", role=REVIEWER)

    def form_data(self, **fields):
        return {
            "title": "La pluie",
            "author": "Contributeurs de Wikipédia",
            "language": "fr",
            "license": License.CC_BY_SA_4,
            "source_url": "https://fr.wikipedia.org/wiki/Pluie",
            "text": "Il pleut[1]. M. Dupont reste chez lui.\nDemain, il sortira.",
            "declaration": "on",
        } | fields

    def test_adding_a_text_needs_an_account(self):
        url = reverse("translations:source_create")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_the_text_is_split_then_checked_then_saved(self):
        self.client.force_login(self.owner)
        url = reverse("translations:source_create")
        response = self.client.post(url, self.form_data())
        self.assertContains(response, "découpé en 3 phrases")
        self.assertEqual(
            response.context["form"]["text"].value(),
            "Il pleut.\nM. Dupont reste chez lui.\n\nDemain, il sortira.",
        )
        self.assertFalse(SourceText.objects.exists())

        checked = "Il pleut.\nM. Dupont reste chez lui.\nDemain, il sortira."
        response = self.client.post(url, self.form_data(text=checked, segmented="1"))
        source = SourceText.objects.get()
        self.assertRedirects(response, source.get_absolute_url())
        self.assertEqual(source.added_by, self.owner)
        self.assertEqual(source.segments.count(), 3)
        self.assertFalse(source.segments.filter(starts_paragraph=True).exclude(order=1).exists())

    def test_a_paragraph_pasted_on_the_checking_step_is_pointed_out_and_split_again(self):
        self.client.force_login(self.owner)
        url = reverse("translations:source_create")
        pasted = "Il pleut. M. Dupont reste chez lui. Demain, il sortira."
        response = self.client.post(url, self.form_data(text=pasted, segmented="1"))
        self.assertContains(response, "découpé en 1 phrase")
        self.assertContains(response, "contient encore plusieurs phrases")
        self.assertFalse(SourceText.objects.exists())

        response = self.client.post(url, self.form_data(text=pasted, segmented="1", resplit="1"))
        self.assertContains(response, "découpé en 3 phrases")
        self.assertNotContains(response, "contient encore plusieurs phrases")
        self.assertEqual(
            response.context["form"]["text"].value(),
            "Il pleut.\nM. Dupont reste chez lui.\nDemain, il sortira.",
        )

    def test_an_unsplit_paragraph_is_saved_when_it_is_confirmed(self):
        self.client.force_login(self.owner)
        pasted = "Il pleut. M. Dupont reste chez lui. Demain, il sortira."
        data = self.form_data(text=pasted, segmented="1", keep="1")
        response = self.client.post(reverse("translations:source_create"), data)
        source = SourceText.objects.get()
        self.assertRedirects(response, source.get_absolute_url())
        self.assertEqual(source.segments.count(), 1)

    def test_declaration_and_license_rules_are_checked(self):
        self.client.force_login(self.owner)
        data = self.form_data(segmented="1", declaration="", source_url="")
        response = self.client.post(reverse("translations:source_create"), data)
        form = response.context["form"]
        self.assertIn("declaration", form.errors)
        self.assertIn("source_url", form.errors)
        self.assertFalse(SourceText.objects.exists())

    def test_new_accounts_cannot_add_links(self):
        newcomer = make_user(email="new@example.org", role=CONTRIBUTOR)
        self.client.force_login(newcomer)
        data = self.form_data(segmented="1", text="Voir www.example.org pour la suite.")
        response = self.client.post(reverse("translations:source_create"), data)
        self.assertIn("text", response.context["form"].errors)
        self.assertFalse(SourceText.objects.exists())

    @override_settings(NEW_ACCOUNT_DAILY_LIMIT=1)
    def test_new_accounts_are_limited(self):
        newcomer = make_user(email="new@example.org", role=CONTRIBUTOR)
        make_source_text(newcomer)
        self.client.force_login(newcomer)
        data = self.form_data(segmented="1", text="Une phrase.")
        response = self.client.post(reverse("translations:source_create"), data)
        self.assertContains(response, "contribution par jour")
        self.assertEqual(SourceText.objects.count(), 1)

    def test_list_and_detail_pages(self):
        source = make_source_text(self.owner, title="Le vent")
        response = self.client.get(reverse("translations:source_list"))
        self.assertContains(response, "Le vent")
        self.assertContains(response, "3 phrases")
        response = self.client.get(source.get_absolute_url())
        self.assertContains(response, "<li>Nous restons à la maison.</li>", html=True)
        self.assertContains(response, "licence libre")
        self.assertContains(response, 'rel="nofollow ugc noopener"')
        self.assertNotContains(response, reverse("translations:source_edit", args=[source.pk]))

    def test_hidden_texts_are_not_shown(self):
        source = make_source_text(self.owner, title="Le vent")
        hide_content(source, self.reviewer)
        self.assertNotContains(self.client.get(reverse("translations:source_list")), "Le vent")
        self.assertEqual(self.client.get(source.get_absolute_url()).status_code, 404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(source.get_absolute_url()), "masqué")

    def test_owner_and_reviewers_edit_the_information(self):
        source = make_source_text(self.owner)
        url = reverse("translations:source_edit", args=[source.pk])
        data = self.form_data(title="La pluie d’automne")
        del data["text"], data["declaration"]

        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, data).status_code, 403)

        for user in (self.owner, self.reviewer):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                data["author"] = user.email.split("@")[0]
                self.assertRedirects(self.client.post(url, data), source.get_absolute_url())
        source.refresh_from_db()
        self.assertEqual(source.title, "La pluie d’automne")
        self.assertEqual(Revision.objects.for_object(source).count(), 3)
        self.assertEqual(Segment.objects.filter(source_text=source).count(), 3)
