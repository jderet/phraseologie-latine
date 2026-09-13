"""One-time tokens sent by email."""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class ActivationTokenGenerator(PasswordResetTokenGenerator):
    """Token of the account activation link.

    It has its own salt, so a password reset token cannot be used to activate an
    account, and it includes the activation state, so it stops working once used.
    """

    key_salt = "accounts.tokens.ActivationTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        return f"{super()._make_hash_value(user, timestamp)}{user.is_active}"


activation_token_generator = ActivationTokenGenerator()
