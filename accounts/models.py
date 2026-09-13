from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Platform user.

    Defined from day one because swapping the user model after the first migration is
    painful. Project fields (display name, ORCID, age confirmation) arrive in step 1.
    """
