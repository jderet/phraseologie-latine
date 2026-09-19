import ast
import gettext

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.tests.factories import make_user
from core.checks import check_legal_pages
from phraseology.models import Attestation, Unit
from phraseology.tests.factories import make_outside_passage

COMPLETE_LEGAL = {
    "publisher_name": "Marcus Tullius",
    "publisher_address": "",
    "contact_email": "contact@example.org",
    "host_name": "Hébergeur exemple",
    "host_address": "1 rue de l’Exemple, Paris",
    "host_phone": "+33 1 00 00 00 00",
}
EMPTY_LEGAL = dict.fromkeys(COMPLETE_LEGAL, "")
LEGAL_PAGES = ["core:legal_notice", "core:privacy", "core:terms"]


class HomePageTests(TestCase):
    def test_renders_in_french_by_default(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="fr" data-theme="auto">')
        self.assertContains(response, "Traduire en latin")

    def test_renders_in_english_when_the_browser_asks(self):
        response = self.client.get(reverse("core:home"), headers={"accept-language": "en"})
        self.assertContains(response, '<html lang="en" data-theme="auto">')
        self.assertContains(response, "Translating into Latin")

    def test_language_switch_remembers_the_choice(self):
        response = self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(response.cookies["django_language"].value, "en")


class HomeShowcaseTests(TestCase):
    """The home page counts the public contents and quotes one validated example."""

    def test_home_counts_and_quotes_a_validated_example(self):
        user = make_user()
        passage, tokens = make_outside_passage(["honesta", "mors", "praestat"])
        unit = Unit.objects.create(reference_form="honesta mors", created_by=user)
        Unit.objects.filter(pk=unit.pk).update(status="validated")
        attestation = Attestation.objects.create(
            unit=unit, passage=passage, created_by=user, is_example=True
        )
        attestation.tokens.set(tokens[:2])
        Attestation.objects.filter(pk=attestation.pk).update(status="validated")

        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "home-quote")
        self.assertContains(response, "honesta")
        self.assertContains(response, "fiches validées")
        self.assertContains(response, "<strong>1</strong>")

    def test_home_without_data_shows_no_quote(self):
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "home-quote")
        self.assertContains(response, "fiches validées")

    def test_a_draft_or_proposed_example_is_not_quoted(self):
        user = make_user()
        passage, tokens = make_outside_passage(["honesta", "mors"])
        unit = Unit.objects.create(reference_form="honesta mors", created_by=user)
        attestation = Attestation.objects.create(
            unit=unit, passage=passage, created_by=user, is_example=True
        )
        attestation.tokens.set(tokens)
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "home-quote")


class ThemeTests(TestCase):
    """The appearance choice is kept in a cookie, without account and without script."""

    def test_theme_choice_is_kept_in_a_cookie(self):
        response = self.client.post(reverse("core:theme"), {"theme": "dark", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(response.cookies["theme"].value, "dark")

    def test_unknown_theme_falls_back_to_auto(self):
        response = self.client.post(reverse("core:theme"), {"theme": "neon", "next": "/"})
        self.assertEqual(response.cookies["theme"].value, "auto")

    def test_redirect_never_leaves_the_site(self):
        response = self.client.post(
            reverse("core:theme"), {"theme": "dark", "next": "https://example.org/"}
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_page_carries_the_chosen_theme(self):
        self.client.cookies["theme"] = "dark"
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, 'data-theme="dark"')

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(reverse("core:theme")).status_code, 405)


class TrainingReservationTests(TestCase):
    """The refusal of model training is readable by robots (cahier des charges, section 5)."""

    def test_robots_txt_excludes_training_robots_from_the_whole_site(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        text = response.content.decode()
        self.assertIn("User-agent: GPTBot\nUser-agent: ClaudeBot\n", text)
        self.assertIn("User-agent: Google-Extended\n", text)
        self.assertRegex(text, r"User-agent: Diffbot\nDisallow: /\n")

    def test_robots_txt_lets_search_robots_in_but_not_into_costly_pages(self):
        text = self.client.get("/robots.txt").content.decode()
        general = text.split("User-agent: *\n", 1)[1]
        self.assertIn("Content-Signal: search=yes, ai-train=no\n", general)
        self.assertIn("Disallow: /recherche/\n", general)
        self.assertIn("Disallow: /compte/\n", general)
        self.assertNotIn("Disallow: /\n", general)

    def test_tdmrep_file_reserves_the_whole_site(self):
        response = self.client.get("/.well-known/tdmrep.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"location": "/", "tdm-reservation": 1}])

    def test_every_response_carries_the_reservation_header(self):
        for url in ["/", "/robots.txt", reverse("api:index")]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url)["tdm-reservation"], "1")

    def test_pages_carry_the_reservation_meta_tag(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, '<meta name="tdm-reservation" content="1">')


@override_settings(LEGAL=COMPLETE_LEGAL)
class LegalPagesTests(TestCase):
    def test_footer_links_to_legal_pages_and_source_code(self):
        response = self.client.get(reverse("core:home"))
        for name in LEGAL_PAGES:
            self.assertContains(response, f'href="{reverse(name)}"')
        self.assertContains(response, f'href="{settings.SOURCE_CODE_URL}"')

    def test_legal_notice_names_publisher_host_and_contact(self):
        response = self.client.get(reverse("core:legal_notice"))
        self.assertContains(response, "Marcus Tullius")
        self.assertContains(response, 'href="mailto:contact@example.org"')
        self.assertContains(response, "1 rue de l’Exemple, Paris")
        self.assertContains(response, "+33 1 00 00 00 00")
        self.assertContains(response, "coordonnées complètes à l’hébergeur")
        self.assertNotContains(response, "à compléter")
        self.assertNotContains(response, "pas encore complète")

    def test_a_published_address_replaces_the_non_professional_note(self):
        with self.settings(LEGAL={**COMPLETE_LEGAL, "publisher_address": "Arpinum"}):
            response = self.client.get(reverse("core:legal_notice"))
        self.assertContains(response, "Arpinum")
        self.assertNotContains(response, "coordonnées complètes à l’hébergeur")

    @override_settings(LEGAL=EMPTY_LEGAL)
    def test_missing_details_are_flagged(self):
        for name in LEGAL_PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "Cette page n’est pas encore complète")
                self.assertContains(response, "à compléter")

    @override_settings(PENDING_SIGNUP_RETENTION_DAYS=7)
    def test_privacy_policy_gives_contact_retention_and_cookies(self):
        response = self.client.get(reverse("core:privacy"))
        self.assertContains(response, "joignable à l’adresse contact@example.org")
        self.assertContains(response, "effacée au bout de 7 jours")
        self.assertContains(response, "<code>sessionid</code>")

    def test_terms_state_the_license_of_contributions(self):
        response = self.client.get(reverse("core:terms"))
        self.assertContains(response, "(CC BY-SA 4.0)")
        self.assertContains(response, "écrivez à contact@example.org")

    def test_legal_pages_are_translated_into_english(self):
        titles = ["Legal notice", "Privacy policy", "Terms of use"]
        for name, title in zip(LEGAL_PAGES, titles, strict=True):
            with self.subTest(page=name):
                response = self.client.get(reverse(name), headers={"accept-language": "en"})
                self.assertContains(response, f"<h1>{title}</h1>")

    def test_signup_page_links_to_terms_and_privacy(self):
        response = self.client.get(reverse("accounts:signup"))
        self.assertContains(response, f'href="{reverse("core:terms")}"')
        self.assertContains(response, f'href="{reverse("core:privacy")}"')


class LegalCheckTests(SimpleTestCase):
    @override_settings(LEGAL=EMPTY_LEGAL)
    def test_deploy_check_warns_while_details_are_missing(self):
        warnings = check_legal_pages(None)
        self.assertEqual([warning.id for warning in warnings], ["core.W001"])
        self.assertIn("host_phone", warnings[0].msg)
        self.assertNotIn("publisher_address", warnings[0].msg)

    @override_settings(LEGAL=COMPLETE_LEGAL)
    def test_deploy_check_passes_when_details_are_complete(self):
        self.assertEqual(check_legal_pages(None), [])


class EnglishTranslationTests(SimpleTestCase):
    """The interface is fully translated into English and the compiled catalog is current.

    The continuous integration runs makemessages first, so a string marked for translation
    but never extracted also makes these tests fail.
    """

    po_path = settings.BASE_DIR / "locale" / "en" / "LC_MESSAGES" / "django.po"

    def entries(self):
        """Yield the fields and flags of each active entry of the catalog."""
        for block in self.po_path.read_text(encoding="utf-8").split("\n\n"):
            fields, flags, current = {}, set(), None
            for line in block.splitlines():
                if line.startswith("#,"):
                    flags.update(flag.strip() for flag in line[2:].split(","))
                elif line.startswith('"') and current:
                    fields[current] += ast.literal_eval(line)
                elif line and not line.startswith("#"):
                    current, _space, value = line.partition(" ")
                    fields[current] = ast.literal_eval(value)
            if fields.get("msgid"):
                yield fields, flags

    def test_every_interface_string_has_an_english_translation(self):
        entries = list(self.entries())
        self.assertGreater(len(entries), 1000)
        missing = [
            fields["msgid"]
            for fields, flags in entries
            if "fuzzy" in flags
            or not all(value for key, value in fields.items() if key.startswith("msgstr"))
        ]
        self.assertEqual(missing, [])

    def test_compiled_catalog_matches_the_translations(self):
        with self.po_path.with_suffix(".mo").open("rb") as compiled:
            catalog = gettext.GNUTranslations(compiled)
        stale = []
        for fields, _flags in self.entries():
            # An entry with a context is looked up with its context.
            context = fields.get("msgctxt")
            if "msgid_plural" in fields:
                plural = (fields["msgid"], fields["msgid_plural"])
                if context is None:
                    found = [catalog.ngettext(*plural, 1), catalog.ngettext(*plural, 2)]
                else:
                    found = [
                        catalog.npgettext(context, *plural, 1),
                        catalog.npgettext(context, *plural, 2),
                    ]
                expected = [fields["msgstr[0]"], fields["msgstr[1]"]]
            elif context is None:
                found, expected = catalog.gettext(fields["msgid"]), fields["msgstr"]
            else:
                found, expected = catalog.pgettext(context, fields["msgid"]), fields["msgstr"]
            if found != expected:
                stale.append(fields["msgid"])
        self.assertEqual(stale, [])


class ContentSecurityPolicyTests(TestCase):
    def test_pages_load_content_from_the_site_only(self):
        policy = self.client.get(reverse("core:home"))["Content-Security-Policy"]
        self.assertIn("default-src 'self'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("form-action 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
