import io
import shutil
import tempfile
from pathlib import Path

from django.core.management import call_command

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG = FIXTURES / "catalog"


class PerseusSourceMixin:
    """A fake Perseus clone for each test: the fixture editions and a .git directory."""

    version = "a" * 40

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name)
        shutil.copytree(FIXTURES / "data", self.source / "data")
        self.set_version(self.version)

    def set_version(self, version):
        heads = self.source / ".git" / "refs" / "heads"
        heads.mkdir(parents=True, exist_ok=True)
        (self.source / ".git" / "HEAD").write_text("ref: refs/heads/master\n")
        (heads / "master").write_text(f"{version}\n")

    def import_corpus(self, *arguments):
        output = io.StringIO()
        call_command(
            "import_perseus",
            "--source",
            str(self.source),
            "--catalog",
            str(CATALOG),
            *arguments,
            stdout=output,
        )
        return output.getvalue()
