import re

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

ORCID_PATTERN = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")


def validate_orcid(value):
    """Check the format of an ORCID iD and its ISO 7064 (11, 2) check character."""
    if not ORCID_PATTERN.fullmatch(value):
        raise ValidationError(
            _("Un identifiant ORCID s’écrit sous la forme 0000-0002-1825-0097."),
            code="orcid_format",
        )
    total = 0
    for digit in value.replace("-", "")[:-1]:
        total = (total + int(digit)) * 2
    remainder = (12 - total % 11) % 11
    if value[-1] != ("X" if remainder == 10 else str(remainder)):
        raise ValidationError(
            _("Cet identifiant ORCID n’existe pas : vérifiez les chiffres."),
            code="orcid_checksum",
        )


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        # Logging in does not depend on the case of the address.
        return self.get(email__iexact=email)

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    create_user.alters_data = True

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    create_superuser.alters_data = True


class User(AbstractUser):
    """Platform user, identified by email address.

    Deleting an account anonymizes it (``accounts.services.anonymize_user``): the row
    stays, so that contributions keep an author.
    """

    username = None
    first_name = None
    last_name = None
    email = models.EmailField(_("adresse e-mail"), unique=True)
    display_name = models.CharField(
        _("nom affiché"),
        max_length=80,
        help_text=_("Nom visible sur vos contributions et votre page publique."),
    )
    orcid = models.CharField(
        "ORCID",
        max_length=19,
        blank=True,
        validators=[validate_orcid],
        help_text=_("Facultatif, par exemple 0000-0002-1825-0097."),
    )
    is_adult = models.BooleanField(_("majorité déclarée"), default=False)
    adult_declared_at = models.DateTimeField(
        _("date de la déclaration de majorité"), null=True, blank=True
    )
    interface_language = models.CharField(
        _("langue d’interface"),
        max_length=8,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
    )
    is_confirmed = models.BooleanField(
        _("compte confirmé"),
        default=False,
        help_text=_(
            "Vrai après une première contribution validée : les limites des nouveaux "
            "comptes ne s’appliquent plus."
        ),
    )
    anonymized_at = models.DateTimeField(_("anonymisé le"), null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self):
        return self.public_name

    def get_absolute_url(self):
        return reverse("accounts:profile", args=[self.pk])

    @property
    def public_name(self):
        """Name shown next to contributions; never the email address."""
        if self.anonymized_at:
            return gettext("Contributeur anonyme")
        return self.display_name

    @property
    def is_pending_activation(self):
        """Registered but the activation link was never used."""
        return not self.is_active and self.last_login is None and self.anonymized_at is None

    def get_full_name(self):
        return self.public_name

    def get_short_name(self):
        return self.public_name
