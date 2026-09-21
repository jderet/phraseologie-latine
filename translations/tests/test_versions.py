from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.limits import ContributionLimitReached, contributions_today
from accounts.roles import CONTRIBUTOR, REVIEWER
from accounts.tests.factories import make_user
from moderation.models import Revision
from moderation.services import revert_to, save_with_revision
from translations.models import Style, TranslatedSegment, TranslationProject, TranslationVersion
from translations.services import publish_version, save_translation

from .factories import make_project, make_published_version, make_source_text, make_version


class TranslationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = make_user(
            email="author@example.org", display_name="Marcus", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.other = make_user(
            email="other@example.org", display_name="Quintus", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.reviewer = make_user(email="reviewer@example.org", display_name="Titus", role=REVIEWER)
        cls.source = make_source_text(cls.author)
        cls.first, cls.second, cls.third = cls.source.segments.all()
        cls.project = make_project(cls.author, cls.source, title="La pluie en latin")


class VersionServicesTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)

    def test_a_new_version_is_a_draft(self):
        self.assertEqual(self.version.state, TranslationVersion.State.DRAFT)
        self.assertIsNone(self.version.published_at)

    def test_saving_a_sentence_records_revisions(self):
        created = save_translation(self.version, self.first, "  Pluit. ", self.author)
        self.assertEqual(created.action, Revision.Action.CREATE)
        self.assertEqual(TranslatedSegment.objects.get().text, "Pluit.")
        updated = save_translation(self.version, self.first, "Pluit hodie.", self.author)
        self.assertEqual(updated.before["text"], "Pluit.")
        self.assertIsNone(save_translation(self.version, self.first, "Pluit hodie.", self.author))
        self.assertIsNone(save_translation(self.version, self.second, " ", self.author))
        self.assertEqual(TranslatedSegment.objects.count(), 1)

    def test_macrons_are_stored_composed(self):
        save_translation(self.version, self.first, "Plūit.", self.author)
        self.assertEqual(TranslatedSegment.objects.get().text, "Plūit.")

    def test_only_the_author_translates_the_sentences_of_the_text(self):
        with self.assertRaises(PermissionDenied):
            save_translation(self.version, self.first, "Pluit.", self.other)
        other_source = make_source_text(self.author, title="Autre texte")
        with self.assertRaises(ValueError):
            save_translation(self.version, other_source.segments.first(), "Pluit.", self.author)

    @override_settings(NEW_ACCOUNT_DAILY_LIMIT=3)
    def test_sentences_do_not_count_toward_the_limit_of_new_accounts(self):
        newcomer = make_user(email="new@example.org", role=CONTRIBUTOR)
        project = make_project(newcomer, self.source)
        version = make_version(newcomer, project)
        for segment, text in zip(self.source.segments.all(), ("A.", "B.", "C."), strict=True):
            save_translation(version, segment, text, newcomer)
        # The project and its translation; a second project goes past the limit.
        self.assertEqual(contributions_today(newcomer), 2)
        with self.assertRaises(ContributionLimitReached):
            make_project(newcomer, self.source, title="Un de trop")
        save_translation(version, self.first, "A et B.", newcomer)
        project.style_note = "breviter"
        save_with_revision(project, newcomer)

    def test_publishing(self):
        with self.assertRaises(ValidationError):
            publish_version(self.version, self.author)
        save_translation(self.version, self.first, "Pluit.", self.author)
        with self.assertRaises(PermissionDenied):
            publish_version(self.version, self.other)
        revision = publish_version(self.version, self.author)
        self.version.refresh_from_db()
        self.assertTrue(self.version.is_published)
        self.assertIsNotNone(self.version.published_at)
        self.assertEqual(revision.after["state"], "published")
        self.assertIsNone(publish_version(self.version, self.author))

    def test_a_published_version_never_goes_back_to_draft(self):
        creation = Revision.objects.for_object(self.version).get()
        save_translation(self.version, self.first, "Pluit.", self.author)
        publish_version(self.version, self.author)
        self.assertIsNone(revert_to(creation, self.author))
        self.version.refresh_from_db()
        self.assertTrue(self.version.is_published)


class VersionVisibilityTests(TranslationTestCase):
    def setUp(self):
        # One project keeps its translation a draft, another publishes its own.
        self.draft = make_version(self.author, self.project)
        self.published = make_published_version(
            self.other, make_project(self.other, self.source, title="Autre projet")
        )

    def test_querysets_return_published_versions_and_own_drafts(self):
        versions = TranslationVersion.objects
        self.assertEqual(list(versions.visible_to(AnonymousUser())), [self.published])
        self.assertCountEqual(versions.visible_to(self.author), [self.draft, self.published])
        self.assertEqual(list(versions.visible_to(self.reviewer)), [self.published])

    def test_drafts_are_shown_to_their_author_only(self):
        translated = save_translation(self.draft, self.first, "Pluit.", self.author).content_object
        urls = [
            reverse("translations:version", args=[self.draft.pk]),
            reverse(
                "moderation:history", args=["translations", "translationversion", self.draft.pk]
            ),
            reverse(
                "moderation:history", args=["translations", "translatedsegment", translated.pk]
            ),
            reverse(
                "moderation:report", args=["translations", "translationversion", self.draft.pk]
            ),
        ]
        for url in urls[:3]:
            self.assertEqual(self.client.get(url).status_code, 404)
        for user in (self.other, self.reviewer):
            self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.author)
        for url in urls[:3]:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_project_page_shows_the_translation_to_its_authors_while_a_draft(self):
        draft_url = self.draft.get_absolute_url()
        other_page = self.client.get(self.published.project.get_absolute_url())
        self.assertContains(other_page, self.published.get_absolute_url())
        self.assertContains(other_page, "phrases traduites : 3 sur 3")
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "La traduction est en préparation")
        self.assertNotContains(response, draft_url)
        self.client.force_login(self.reviewer)
        self.assertNotContains(self.client.get(self.project.get_absolute_url()), draft_url)
        self.client.force_login(self.author)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "brouillon, visible des seuls auteurs")
        self.assertContains(response, draft_url)
        self.assertContains(response, reverse("translations:version_edit", args=[self.draft.pk]))

    def test_published_version_page(self):
        response = self.client.get(self.published.get_absolute_url())
        self.assertContains(response, "La traduction")
        self.assertContains(response, "Domi manemus.")
        self.assertContains(response, "CC BY-SA 4.0")
        self.assertNotContains(
            response, reverse("translations:version_edit", args=[self.published.pk])
        )


class TranslationPagesTests(TranslationTestCase):
    def test_project_creation(self):
        url = reverse("translations:project_create", args=[self.source.pk])
        self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(url), 'value="La pluie"')
        response = self.client.post(
            url,
            {
                "title": "Pluie",
                "style": Style.TACITEAN,
                "style_note": "Annales",
                "description": "Pour débuter.",
            },
        )
        project = TranslationProject.objects.get(title="Pluie")
        main = project.main_version
        self.assertRedirects(response, reverse("translations:version_edit", args=[main.pk]))
        self.assertEqual((project.created_by, project.source_text), (self.other, self.source))
        self.assertEqual((project.style, project.style_note), (Style.TACITEAN, "Annales"))
        self.assertEqual((main.author, main.is_draft), (self.other, True))
        page = self.client.get(self.source.get_absolute_url())
        self.assertContains(page, "Pluie")
        self.assertContains(page, "tacitéen")

    def test_project_information_is_edited_by_its_creator_or_a_reviewer(self):
        url = reverse("translations:project_edit", args=[self.project.pk])
        self.client.force_login(self.other)
        data = {"title": "Autre", "style": Style.LIVIAN}
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.reviewer)
        self.assertRedirects(self.client.post(url, data), self.project.get_absolute_url())
        self.project.refresh_from_db()
        self.assertEqual(self.project.style, Style.LIVIAN)

    def test_no_version_is_started_from_nothing(self):
        self.client.force_login(self.other)
        url = reverse("translations:version_create", args=[self.project.pk])
        self.assertRedirects(self.client.post(url), self.project.get_absolute_url())
        self.assertEqual(list(TranslationVersion.objects.all()), [self.project.main_version])

    def test_editor_saves_the_sentences(self):
        version = make_version(self.author, self.project)
        url = reverse("translations:version_edit", args=[version.pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Nous restons à la maison.")
        data = {
            f"s{self.first.pk}": "Pluit.",
            f"s{self.second.pk}": "",
            f"s{self.third.pk}": "Cras.",
        }
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "2 phrases enregistrées.")
        self.assertEqual(
            list(version.segments.values_list("segment__order", "text")),
            [(1, "Pluit."), (3, "Cras.")],
        )
        self.assertContains(self.client.post(url, data, follow=True), "Aucune modification.")

    def test_editor_is_for_the_author_only(self):
        version = make_version(self.author, self.project)
        url = reverse("translations:version_edit", args=[version.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        published = make_published_version(
            self.other, make_project(self.other, self.source, title="Autre projet")
        )
        self.client.force_login(self.author)
        url = reverse("translations:version_edit", args=[published.pk])
        self.assertEqual(self.client.post(url, {f"s{self.first.pk}": "Nix."}).status_code, 403)

    def test_editor_refuses_links_from_new_accounts(self):
        newcomer = make_user(email="new@example.org", role=CONTRIBUTOR)
        version = make_version(newcomer, make_project(newcomer, self.source, title="Nouveau"))
        self.client.force_login(newcomer)
        url = reverse("translations:version_edit", args=[version.pk])
        data = {f"s{self.first.pk}": "Pluit.", f"s{self.second.pk}": "vide www.example.org"}
        response = self.client.post(url, data)
        self.assertContains(response, "Rien n’est enregistré")
        self.assertContains(response, "Les liens ne sont pas autorisés")
        self.assertFalse(TranslatedSegment.objects.exists())

    def test_publication(self):
        version = make_version(self.author, self.project)
        url = reverse("translations:version_publish", args=[version.pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.post(url, follow=True), "Traduisez au moins une phrase")
        save_translation(version, self.first, "Pluit.", self.author)
        self.assertContains(self.client.get(url), "Phrases traduites : 1 sur 3")
        self.assertRedirects(self.client.post(url), version.get_absolute_url())
        version.refresh_from_db()
        self.assertTrue(version.is_published)
        self.client.logout()
        self.assertContains(self.client.get(version.get_absolute_url()), "non traduite")
