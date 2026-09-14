"""Identity details shown in the legal pages, read from settings.LEGAL."""

from django.conf import settings

# The publisher's address may stay private: a non-professional publisher can give the
# host's details instead.
REQUIRED_FIELDS = ["publisher_name", "contact_email", "host_name", "host_address", "host_phone"]


def missing_fields():
    return [field for field in REQUIRED_FIELDS if not settings.LEGAL.get(field)]
