"""Exports of a version: a bilingual text file. The printable page with notes is a template."""

from django.utils.formats import date_format
from django.utils.text import slugify
from django.utils.translation import gettext


def export_filename(version, extension):
    parts = [slugify(version.project.title), slugify(version.author.public_name)]
    name = "-".join(part for part in parts if part) or f"version-{version.pk}"
    return f"{name}.{extension}"


def bilingual_text(version, rows, step=None):
    """The source text and the Latin, sentence by sentence, with the licenses to credit.

    ``step`` is the step whose text the rows give; None for the working text.
    """
    project, source = version.project, version.project.source_text
    lines = [project.title, "=" * len(project.title), ""]
    lines.append(
        gettext("%(version)s, style %(style)s.")
        % {"version": version.display_name, "style": project.get_style_display()}
    )
    if version.is_draft:
        lines.append(gettext("Brouillon non publié."))
    if step is not None:
        lines.append(
            gettext("Étape %(number)d du %(date)s : %(message)s")
            % {
                "number": step.number,
                "date": date_format(step.created_at, "DATE_FORMAT"),
                "message": step.message,
            }
        )
    lines.append(
        gettext("Texte source : %(title)s, %(license)s.")
        % {"title": source.title, "license": source.get_license_display()}
    )
    if source.author:
        author = source.author
        if source.author_dates:
            author = f"{author} ({source.author_dates})"
        lines.append(gettext("Auteur du texte source : %(author)s.") % {"author": author})
    if source.source_url:
        lines.append(gettext("Origine : %(url)s") % {"url": source.source_url})
    lines.append(gettext("Traduction latine sous licence CC BY-SA 4.0."))
    for row in rows:
        segment, number = row["segment"], row["number"]
        lines.append("")
        if segment.starts_paragraph and number > 1:
            lines.append("")
        if segment.level:
            lines.append(f"{'#' * segment.level} {segment.text}")
            if row["saved"]:
                lines.append(f"{'#' * segment.level} {row['saved']}")
            continue
        latin = row["saved"] or gettext("[non traduite]")
        lines.append(f"{number}. {segment.text}")
        lines.append(f"   {latin}")
    return "\n".join(lines) + "\n"
