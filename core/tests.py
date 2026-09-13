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
