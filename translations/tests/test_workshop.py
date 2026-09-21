from django.urls import reverse

from .test_versions import TranslationTestCase


class ProjectTabsTests(TranslationTestCase):
    def test_project_page_shows_its_tabs(self):
        response = self.client.get(reverse("translations:project", args=[self.project.pk]))
        self.assertContains(response, 'class="workshop-tabs"')
        self.assertContains(
            response, reverse("translations:project_compare", args=[self.project.pk])
        )
        self.assertContains(response, reverse("translations:topic_list", args=[self.project.pk]))

    def test_compare_page_marks_its_tab(self):
        response = self.client.get(reverse("translations:project_compare", args=[self.project.pk]))
        self.assertContains(response, 'aria-current="page">Comparer<')


class FirstStepsTests(TranslationTestCase):
    def test_first_steps_are_shown_until_closed(self):
        url = reverse("translations:project", args=[self.project.pk])
        self.assertContains(self.client.get(url), "Premiers pas")
        response = self.client.post(reverse("translations:hide_first_steps"), {"next": url})
        self.assertRedirects(response, url)
        self.assertEqual(response.cookies["first_steps"].value, "hidden")
        self.assertNotContains(self.client.get(url), "Premiers pas")

    def test_closing_never_redirects_elsewhere(self):
        response = self.client.post(
            reverse("translations:hide_first_steps"), {"next": "https://example.com/"}
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_help_page(self):
        response = self.client.get(reverse("translations:help"))
        self.assertContains(response, "Traduire ici")
