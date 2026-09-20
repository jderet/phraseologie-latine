"""What the templates need about the divisions of a source text."""

from django import template

from ..sources import Place

register = template.Library()


@register.filter
def division_label(source, division):
    """« Chapitre 2 », with the name this text gives to that level of title."""
    return source.citation(Place(division))
