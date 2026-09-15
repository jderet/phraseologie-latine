"""Heavy queries stopped by the statement timeout (settings.DATABASE_STATEMENT_TIMEOUT)."""

from django.db import OperationalError, connection, transaction
from psycopg.errors import QueryCanceled


def _statement_timeout(cursor):
    """The statement timeout of the connection, in milliseconds; 0 when there is none."""
    cursor.execute("SELECT setting::integer FROM pg_settings WHERE name = 'statement_timeout'")
    return cursor.fetchone()[0]


def _set_statement_timeout(cursor, milliseconds):
    cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(milliseconds)])


class TimeLimit:
    """Run heavy queries in a savepoint and turn a canceled query into a flag.

        with TimeLimit() as limit:
            ...
        if limit.exceeded:
            ...

    The savepoint keeps the connection usable after the cancellation, even inside a
    transaction; any other error goes through. With ``seconds``, the queries of the block
    also stop after that time, even where the site sets no timeout (on the Mac); the timeout
    of the site still applies when it is shorter.
    """

    def __init__(self, seconds=None):
        self.exceeded = False
        self.seconds = seconds if connection.vendor == "postgresql" else None
        self._previous = None
        self._atomic = transaction.atomic()

    def __enter__(self):
        self._atomic.__enter__()
        if self.seconds:
            with connection.cursor() as cursor:
                self._previous = _statement_timeout(cursor)
                limit = int(self.seconds * 1000)
                if self._previous:
                    limit = min(limit, self._previous)
                _set_statement_timeout(cursor, limit)
        return self

    def __exit__(self, kind, error, traceback):
        if self.seconds and error is None:
            # A setting changed in a savepoint outlives it: the previous timeout comes back.
            # After a canceled query, rolling back the savepoint restores it already.
            with connection.cursor() as cursor:
                _set_statement_timeout(cursor, self._previous)
        self._atomic.__exit__(kind, error, traceback)
        if isinstance(error, OperationalError) and isinstance(error.__cause__, QueryCanceled):
            self.exceeded = True
            return True
        return False
