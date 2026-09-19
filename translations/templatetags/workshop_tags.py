"""Navigation of the translation workshop: the tabs of a project, the first steps box."""

from django import template

from ..workshop import project_counts

register = template.Library()

FIRST_STEPS_COOKIE = "first_steps"


@register.inclusion_tag("translations/project_tabs.html", takes_context=True)
def project_tabs(context, project, active):
    """The tabs of a project, like those of a repository; each is a plain link."""
    return {
        "project": project,
        "active": active,
        "counts": project_counts(context.get("user"), project),
    }


@register.inclusion_tag("translations/first_steps.html", takes_context=True)
def first_steps(context, where):
    """A short help for newcomers, until they close it (remembered in a cookie)."""
    request = context.get("request")
    hidden = request is not None and request.COOKIES.get(FIRST_STEPS_COOKIE) == "hidden"
    return {
        "hidden": hidden,
        "where": where,
        "next": request.get_full_path() if request is not None else "/",
        "csrf_token": context.get("csrf_token"),
    }
