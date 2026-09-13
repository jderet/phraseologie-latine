from django import template

from ..forms import CommentForm
from ..registry import comment_url, history_url, report_url, vote_url
from ..services import can_comment, can_vote, comments_for, vote_summary

register = template.Library()


@register.inclusion_tag("moderation/links.html", takes_context=True)
def moderation_links(context, obj):
    """Links to the history of a content and to the report form."""
    return {
        "history_url": history_url(obj),
        "report_url": report_url(obj),
        "user": context.get("user"),
    }


@register.inclusion_tag("moderation/discussion.html", takes_context=True)
def discussion(context, obj, closed_message=""):
    """The messages about a content, and the form to post one when the user may."""
    user = context.get("user")
    return {
        "comments": comments_for(user, obj),
        "can_comment": can_comment(user, obj),
        "post_url": comment_url(obj),
        "form": CommentForm(),
        "closed_message": closed_message,
        "user": user,
        "csrf_token": context.get("csrf_token"),
    }


@register.inclusion_tag("moderation/votes.html", takes_context=True)
def votes(context, obj, for_label, against_label, note=""):
    """The indicative votes on a content, and the buttons to vote when the user may."""
    user = context.get("user")
    return {
        "summary": vote_summary(user, obj),
        "can_vote": can_vote(user, obj),
        "vote_url": vote_url(obj),
        "for_label": for_label,
        "against_label": against_label,
        "note": note,
        "csrf_token": context.get("csrf_token"),
    }
