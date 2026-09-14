"""The private notebook of a reader: highlights, private notes and lists of passages.

A notebook is no contribution: nobody else sees it, neither the API nor the exports carry it,
as for a draft (rule 8), and deleting the account deletes it.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from corpus.models import Passage, Token


class Highlight(models.Model):
    class Color(models.TextChoices):
        YELLOW = "yellow", _("jaune")
        GREEN = "green", _("vert")
        BLUE = "blue", _("bleu")
        PINK = "pink", _("rose")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="highlights",
        verbose_name=_("propriétaire"),
    )
    passage = models.ForeignKey(
        Passage, on_delete=models.PROTECT, related_name="+", verbose_name=_("passage")
    )
    # Stable word identifiers (rule 1).
    tokens = models.ManyToManyField(Token, related_name="+", verbose_name=_("mots"))
    color = models.CharField(
        _("couleur"), max_length=10, choices=Color.choices, default=Color.YELLOW
    )
    created_at = models.DateTimeField(_("créé le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("surlignage")
        verbose_name_plural = _("surlignages")
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.passage} · {self.get_color_display()}"


class PrivateNote(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_notes",
        verbose_name=_("propriétaire"),
    )
    passage = models.ForeignKey(
        Passage, on_delete=models.PROTECT, related_name="+", verbose_name=_("passage")
    )
    tokens = models.ManyToManyField(Token, related_name="+", verbose_name=_("mots"))
    text = models.TextField(_("note"), max_length=2000)
    created_at = models.DateTimeField(_("créée le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("note privée")
        verbose_name_plural = _("notes privées")
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.passage} · {self.text[:40]}"


class PassageList(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="passage_lists",
        verbose_name=_("propriétaire"),
    )
    name = models.CharField(_("nom"), max_length=100)
    passages = models.ManyToManyField(
        Passage, through="PassageListEntry", related_name="+", verbose_name=_("passages")
    )
    created_at = models.DateTimeField(_("créée le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("liste de passages")
        verbose_name_plural = _("listes de passages")
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="notebook_one_list_name"),
        ]

    def __str__(self):
        return self.name


class PassageListEntry(models.Model):
    passage_list = models.ForeignKey(
        PassageList, on_delete=models.CASCADE, related_name="entries", verbose_name=_("liste")
    )
    passage = models.ForeignKey(
        Passage, on_delete=models.PROTECT, related_name="+", verbose_name=_("passage")
    )
    added_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("passage d’une liste")
        verbose_name_plural = _("passages des listes")
        ordering = ["added_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["passage_list", "passage"], name="notebook_one_entry_per_passage"
            ),
        ]

    def __str__(self):
        return f"{self.passage_list} · {self.passage}"
