from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.roles import ADMINISTRATOR
from accounts.tests.factories import make_user
from moderation.models import Revision
from phraseology.models import Unit

from .test_units import PhraseologyTestCase

WRITTEN_AS_UD = "redigo -obl-> memoria; memoria -case-> in"


class ConvertSchemasTests(PhraseologyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.administrator = make_user(
            email="admin@example.org", display_name="Gaius", role=ADMINISTRATOR
        )
        # A draft of another account is converted too.
        cls.draft = Unit.objects.create(
            reference_form="in memoriam redigere", schema=WRITTEN_AS_UD, created_by=cls.other
        )
        cls.kept = Unit.objects.create(
            reference_form="res publica",
            schema="res -amod-> publicus",
            status=Unit.Status.PROPOSED,
            created_by=cls.author,
        )
        # A schema written otherwise than it would be now, without prepositional phrase, stays.
        cls.not_normalized = Unit.objects.create(
            reference_form="vir bonus",
            schema="vir -amod-> bonus",
            status=Unit.Status.PROPOSED,
            created_by=cls.author,
        )

    def test_a_dry_run_lists_the_schemas(self):
        output = StringIO()
        call_command("convert_schemas", "--dry-run", stdout=output)
        self.assertIn("in memoriam redigere", output.getvalue())
        self.assertIn("1 schéma à convertir.", output.getvalue())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.schema, WRITTEN_AS_UD)

    def test_an_administrator_is_needed(self):
        for arguments in ([], ["--email=author@example.org"], ["--email=nobody@example.org"]):
            with self.subTest(arguments=arguments), self.assertRaises(CommandError):
                call_command("convert_schemas", *arguments, stdout=StringIO())

    def test_each_schema_converted_is_a_revision(self):
        output = StringIO()
        call_command("convert_schemas", "--email=ADMIN@example.org", stdout=output)
        self.assertIn("1 schéma converti.", output.getvalue())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.schema, "redigo -sp-> in; in -reg-> memoria")
        revision = Revision.objects.get(author=self.administrator)
        self.assertEqual(revision.object_id, self.draft.pk)
        self.assertIn("Schéma converti", revision.comment)
        self.kept.refresh_from_db()
        self.assertEqual(self.kept.schema, "res -amod-> publicus")
        self.not_normalized.refresh_from_db()
        self.assertEqual(self.not_normalized.schema, "vir -amod-> bonus")
        # A second run finds nothing left to convert.
        call_command("convert_schemas", "--email=admin@example.org", stdout=output)
        self.assertIn("0 schémas convertis.", output.getvalue())
