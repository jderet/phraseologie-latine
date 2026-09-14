from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.checks import check_legal_pages

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
        self.assertContains(response, '<html lang="fr">')
        self.assertContains(response, "Traduire en latin")

    def test_renders_in_english_when_the_browser_asks(self):
        response = self.client.get(reverse("core:home"), headers={"accept-language": "en"})
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, "Translating into Latin")

    def test_language_switch_remembers_the_choice(self):
        response = self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(response.cookies["django_language"].value, "en")


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
