"""Heavy queries stopped by the statement timeout (settings.DATABASE_STATEMENT_TIMEOUT)."""

from django.db import OperationalError, transaction
from psycopg.errors import QueryCanceled


class TimeLimit:
    """Run heavy queries in a savepoint and turn a canceled query into a flag.

        with TimeLimit() as limit:
            ...
        if limit.exceeded:
            ...

    The savepoint keeps the connection usable after the cancellation, even inside a
    transaction; any other error goes through.
    """

    def __init__(self):
        self.exceeded = False
        self._atomic = transaction.atomic()

    def __enter__(self):
        self._atomic.__enter__()
        return self

    def __exit__(self, kind, error, traceback):
        self._atomic.__exit__(kind, error, traceback)
        if isinstance(error, OperationalError) and isinstance(error.__cause__, QueryCanceled):
            self.exceeded = True
            return True
        return False
