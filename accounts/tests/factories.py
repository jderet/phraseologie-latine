"""Helpers to create test data, shared with the tests of other applications."""

from django.contrib.auth.models import Group

from accounts.models import User

PASSWORD = "Tusculum-45"


def make_user(email="cicero@example.org", password=PASSWORD, role=None, **fields):
    fields.setdefault("display_name", "Cicero")
    user = User.objects.create_user(email=email, password=password, **fields)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user
