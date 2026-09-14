from django.test import TestCase
from django.urls import reverse


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
