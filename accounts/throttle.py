"""Limits on repeated attempts against one address: logins, activation and reset emails.

Counters live in the cache, keyed by a hash of the address typed, so neither the address
nor an IP address is stored; they expire on their own.
"""

import hashlib
from dataclasses import dataclass

from django.core.cache import cache


@dataclass(frozen=True)
class Throttle:
    name: str
    limit: int
    period: int  # seconds, counted from the first attempt

    def key(self, email):
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        return f"throttle:{self.name}:{digest}"

    def is_blocked(self, email):
        return cache.get(self.key(email), 0) >= self.limit

    def hit(self, email):
        key = self.key(email)
        if cache.add(key, 1, self.period):
            return
        try:
            cache.incr(key)
        except ValueError:  # expired since add()
            cache.add(key, 1, self.period)

    def reset(self, email):
        cache.delete(self.key(email))


LOGIN_FAILURES = Throttle("login", limit=5, period=15 * 60)
ACTIVATION_EMAILS = Throttle("activation", limit=3, period=60 * 60)
RESET_EMAILS = Throttle("reset", limit=3, period=60 * 60)
ADMIN_PASSWORD_CHANGES = Throttle("admin-password", limit=10, period=60 * 60)
