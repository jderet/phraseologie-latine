from unittest import mock, skipUnless

from django.db import OperationalError, connection
from django.test import TestCase
from django.urls import reverse
from psycopg.errors import QueryCanceled

from accounts.models import User
from corpus.timeouts import TimeLimit

from .utils import PerseusSourceMixin


def canceled_query(*args, **kwargs):
    """Raise the error Django gives when the statement timeout cancels a query."""
    message = "canceling statement due to statement timeout"
    try:
        raise QueryCanceled(message)
    except QueryCanceled as cause:
        raise OperationalError(message) from cause


@skipUnless(connection.vendor == "postgresql", "statement_timeout is a PostgreSQL setting")
class TimeLimitTests(TestCase):
    def test_a_canceled_query_is_reported_and_the_connection_stays_usable(self):
        with TimeLimit() as limit, connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = 10")
            cursor.execute("SELECT pg_sleep(1)")
        self.assertTrue(limit.exceeded)
        self.assertEqual(User.objects.count(), 0)
        with connection.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            self.assertEqual(cursor.fetchone()[0], "0")

    def test_queries_within_the_limit_run_normally(self):
        with TimeLimit() as limit:
            count = User.objects.count()
        self.assertFalse(limit.exceeded)
        self.assertEqual(count, 0)

    def test_other_errors_go_through(self):
        with self.assertRaises(ZeroDivisionError), TimeLimit():
            raise ZeroDivisionError


class TooBroadSearchTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()

    def test_pages_ask_to_narrow_a_search_stopped_by_the_time_limit(self):
        query = {"term1": "custos", "scope": "all"}
        for name in ["corpus:search", "corpus:search_fragment"]:
            with (
                self.subTest(page=name),
                mock.patch("corpus.views.author_distribution", side_effect=canceled_query),
            ):
                response = self.client.get(reverse(name), query)
                self.assertContains(response, "La recherche a pris trop de temps")
                self.assertFalse(response.context["searched"])
