"""The annotation guide: publishing a version, and reading its text written with a light markup.

A line "## Title" or "### Title" makes a heading with an anchor, lines beginning with "- " make
a list, and a blank line ends a paragraph. Nothing else is interpreted: the text is escaped.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.html import format_html, format_html_join
from django.utils.text import slugify

from accounts.roles import is_administrator

from .models import GuideVersion


def render_guide(text):
    """The HTML of a version of the guide, every piece of its text escaped."""
    blocks, paragraph, items = [], [], []

    def end_paragraph():
        if paragraph:
            blocks.append(format_html("<p>{}</p>", " ".join(paragraph)))
            paragraph.clear()

    def end_list():
        if items:
            entries = format_html_join("", "<li>{}</li>", ((item,) for item in items))
            blocks.append(format_html("<ul>{}</ul>", entries))
            items.clear()

    for line in text.splitlines():
        line = line.strip()
        level = 3 if line.startswith("### ") else 2 if line.startswith("## ") else 0
        if level:
            end_paragraph()
            end_list()
            title = line[level + 1 :].strip()
            blocks.append(format_html('<h{} id="{}">{}</h{}>', level, slugify(title), title, level))
        elif line.startswith("- "):
            end_paragraph()
            items.append(line[2:].strip())
        elif not line:
            end_paragraph()
            end_list()
        else:
            end_list()
            paragraph.append(line)
    end_paragraph()
    end_list()
    return format_html_join("\n", "{}", ((block,) for block in blocks))


@transaction.atomic
def publish_guide(text, summary, user):
    """An administrator publishes a new version of the guide; the previous ones stay."""
    if not is_administrator(user):
        raise PermissionDenied
    latest = GuideVersion.objects.select_for_update().order_by("-number").first()
    number = (latest.number if latest else 0) + 1
    return GuideVersion.objects.create(number=number, text=text, summary=summary, published_by=user)
