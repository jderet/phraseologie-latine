from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase

from accounts.roles import CONTRIBUTOR, REVIEWER
from accounts.tests.factories import make_user

from .models import ModerationTestNote


class ModerationTestCase(TestCase):
    """Creates the table of the test-only content model, kept until the test database goes.

    Once imported, the model stays known to Django for the whole run: deleting a user in any
    later test looks for notes pointing to that user, so the table must still exist.
    """

    @classmethod
    def setUpClass(cls):
        if ModerationTestNote._meta.db_table not in connection.introspection.table_names():
            with connection.schema_editor() as editor:
                editor.create_model(ModerationTestNote)
        # Migrations do not know this model, so its content type is created here, outside
        # the test transactions: one created inside a test would be rolled back but stay
        # in the content type cache.
        ContentType.objects.clear_cache()
        ContentType.objects.get_for_model(ModerationTestNote)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(
            email="owner@example.org", display_name="Owner", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.other = make_user(
            email="other@example.org", display_name="Other", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.reviewer = make_user(
            email="reviewer@example.org", display_name="Reviewer", role=REVIEWER
        )
        cls.newcomer = make_user(
            email="newcomer@example.org", display_name="Newcomer", role=CONTRIBUTOR
        )
