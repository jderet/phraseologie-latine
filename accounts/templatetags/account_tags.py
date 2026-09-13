from django import template

from accounts import roles

register = template.Library()


@register.filter
def is_reviewer(user):
    return roles.is_reviewer(user)
