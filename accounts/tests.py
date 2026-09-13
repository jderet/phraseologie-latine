from django.contrib.auth import get_user_model
from django.test import TestCase


class CustomUserModelTests(TestCase):
    def test_project_uses_the_custom_user_model(self):
        self.assertEqual(get_user_model()._meta.label, "accounts.User")

    def test_create_user_with_password(self):
        user = get_user_model().objects.create_user(username="cicero", password="Tusculum-45")
        self.assertTrue(user.check_password("Tusculum-45"))
