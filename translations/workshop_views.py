"""Pages of the translation workshop around the versions: help, tabs of a project."""

import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from activity.feeds import project_feed
from moderation.registry import can_view
from moderation.services import save_with_revision

from . import glossary as glossary_services
from . import members as member_services
from . import topics as topic_services
from .concordance import LATIN, SOURCE, highlight, search
from .forms import GlossaryEntryForm, InviteForm, TopicForm
from .models import (
    GlossaryEntry,
    Topic,
    TranslationProject,
    TranslationVersion,
    VersionMember,
    is_version_writer,
)
from .permissions import can_edit, can_manage
from .sources import SourceHistory
from .templatetags.workshop_tags import FIRST_STEPS_COOKIE
from .views import _contribute, _paginate, _visible


@require_GET
def help_page(request):
    return render(request, "translations/help.html")


def _safe_next(request, fallback="/"):
    next_url = request.POST.get("next") or request.GET.get("next") or fallback
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return fallback
    return next_url


@require_POST
def hide_first_steps(request):
    """Close the first steps box for good, remembered in a cookie; no account needed."""
    response = redirect(_safe_next(request))
    response.set_cookie(FIRST_STEPS_COOKIE, "hidden", max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


def project_activity(request, pk):
    """What happened lately in a project: publications, steps, proposals, messages."""
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    return render(
        request,
        "translations/project_activity.html",
        {"project": project, "events": project_feed(request.user, project)},
    )


# Co-authors


def _members_version(user, pk):
    """A version the user may see, or one they are invited to co-author."""
    version = get_object_or_404(
        TranslationVersion.objects.select_related("project", "author"), pk=pk
    )
    invited = (
        user.is_authenticated
        and version.members.filter(user=user, status=VersionMember.Status.INVITED).exists()
    )
    if not (can_view(user, version) or invited):
        raise Http404
    return version


@require_http_methods(["GET", "POST"])
def version_members(request, pk):
    """The co-authors of a version; its author invites and removes them."""
    user = request.user
    version = _members_version(user, pk)
    manager = can_manage(user, version)
    form = InviteForm(request.POST or None)
    if request.method == "POST":
        if not manager:
            raise Http404
        if form.is_valid():
            try:
                invitee = member_services.find_invitee(form.cleaned_data["name"])
                member, saved = _contribute(request, member_services.invite, version, user, invitee)
            except ValidationError as error:
                form.add_error("name", error)
            else:
                if saved:
                    messages.success(
                        request,
                        _("%(name)s est invité : il ou elle doit accepter l’invitation.")
                        % {"name": member.user.public_name},
                    )
                    return redirect("translations:version_members", version.pk)
    shown = [
        member
        for member in version.members.select_related("user", "invited_by")
        if can_view(user, member)
        and (member.status in (VersionMember.Status.INVITED, VersionMember.Status.ACTIVE))
    ]
    own = next((member for member in shown if member.user_id == user.pk), None)
    return render(
        request,
        "translations/version_members.html",
        {
            "version": version,
            "project": version.project,
            "members": shown,
            "own": own,
            "can_manage": manager,
            "is_writer": is_version_writer(user, version),
            "form": form if manager else None,
        },
    )


@login_required
@require_POST
def member_answer(request, pk):
    member = get_object_or_404(VersionMember.objects.select_related("version"), pk=pk)
    decision = request.POST.get("decision")
    if decision not in ("accept", "decline"):
        return HttpResponseBadRequest()
    try:
        member_services.answer(member, request.user, accept=decision == "accept")
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect("translations:version_members", member.version_id)
    if decision == "accept":
        messages.success(request, _("Vous êtes co-auteur de cette version."))
        return redirect("translations:version_edit", member.version_id)
    messages.success(request, _("L’invitation est refusée."))
    return redirect("translations:project", member.version.project_id)


@login_required
@require_POST
def member_remove(request, pk):
    member = get_object_or_404(VersionMember.objects.select_related("version"), pk=pk)
    try:
        member_services.remove(member, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if request.user.pk == member.user_id:
            messages.success(request, _("Vous n’êtes plus co-auteur de cette version."))
            return redirect("translations:project", member.version.project_id)
        messages.success(request, _("La personne n’est plus co-autrice de cette version."))
    return redirect("translations:version_members", member.version_id)


# Topics


def _project(user, pk):
    return _visible(
        user, TranslationProject.objects.select_related("source_text", "created_by"), pk
    )


def _topic(user, project, number):
    topic = get_object_or_404(
        project.topics.select_related("author", "closed_by", "segment"), number=number
    )
    topic.project = project
    if not can_view(user, topic):
        raise Http404
    return topic


TOPIC_STATES = {"ouverts": Topic.Status.OPEN, "fermes": Topic.Status.CLOSED}


def topic_list(request, pk):
    """The subjects of a project, open ones by default, filtered by label."""
    project = _project(request.user, pk)
    state = request.GET.get("etat") if request.GET.get("etat") in TOPIC_STATES else "ouverts"
    label = request.GET.get("etiquette") if request.GET.get("etiquette") in Topic.Label else ""
    queryset = project.topics.filter(status=TOPIC_STATES[state]).select_related("author")
    if label:
        queryset = queryset.filter(labels__contains=[label])
    topics = []
    for topic in queryset.order_by("-number"):
        topic.project = project
        if can_view(request.user, topic):
            topics.append(topic)
    counts = {
        name: project.topics.filter(status=status, is_hidden=False).count()
        for name, status in TOPIC_STATES.items()
    }
    return render(
        request,
        "translations/topic_list.html",
        {
            "project": project,
            "page": _paginate(request, topics),
            "state": state,
            "label": label,
            "labels": Topic.Label.choices,
            "state_counts": counts,
            "can_open": topic_services.can_open_topic(request.user, project),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def topic_create(request, pk):
    project = _project(request.user, pk)
    if not topic_services.can_open_topic(request.user, project):
        raise Http404
    initial = {}
    if request.GET.get("phrase", "").isdigit():
        initial["sentence"] = int(request.GET["phrase"])
    form = TopicForm(request.POST or None, user=request.user, project=project, initial=initial)
    if request.method == "POST" and form.is_valid():
        topic = form.save()
        topic.project = project
        topic, saved = _contribute(request, topic_services.open_topic, topic, request.user)
        if saved:
            messages.success(request, _("Le sujet est ouvert."))
            return redirect(topic)
    return render(request, "translations/topic_form.html", {"project": project, "form": form})


def topic_detail(request, pk, number):
    project = _project(request.user, pk)
    topic = _topic(request.user, project, number)
    sentence_number = None
    if topic.segment_id:
        numbers = SourceHistory(project.source_text).numbers_at()
        sentence_number = numbers.get(topic.segment.latest.pk)
    return render(
        request,
        "translations/topic_detail.html",
        {
            "project": project,
            "topic": topic,
            "body": topic_services.linked_text(request.user, topic.body, project),
            "sentence_number": sentence_number,
            "can_close": topic_services.can_close_topic(request.user, topic),
            "can_edit": can_edit(request.user, topic),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def topic_edit(request, pk, number):
    project = _project(request.user, pk)
    topic = _topic(request.user, project, number)
    if not can_edit(request.user, topic):
        raise PermissionDenied
    form = TopicForm(request.POST or None, instance=topic, user=request.user, project=project)
    if request.method == "POST" and form.is_valid():
        topic = form.save()
        topic.labels = topic_services.clean_labels(topic.labels)
        revision, saved = _contribute(request, save_with_revision, topic, request.user)
        if saved:
            messages.success(
                request, _("Le sujet est modifié.") if revision else _("Aucune modification.")
            )
            return redirect(topic)
    return render(
        request,
        "translations/topic_form.html",
        {"project": project, "form": form, "topic": topic},
    )


@login_required
@require_POST
def topic_status(request, pk, number):
    project = _project(request.user, pk)
    topic = _topic(request.user, project, number)
    open_ = request.POST.get("etat") == "ouvrir"
    topic_services.set_topic_status(topic, request.user, open_)
    messages.success(request, _("Le sujet est rouvert.") if open_ else _("Le sujet est fermé."))
    return redirect(topic)


# Concordance of the translations


@require_GET
def concordance(request):
    """Where a word appears in the published versions, Latin and source side by side.

    With ``fragment``, only the results, for the side panel of the editor.
    """
    query = request.GET.get("q", "")[:200]
    side = request.GET.get("cote") if request.GET.get("cote") == SOURCE else LATIN
    results, exceeded = search(query, side)
    for result in results:
        result["latin_marked"] = highlight(result["latin"], query) if side == LATIN else None
        result["source_marked"] = (
            highlight(result["segment"].text, query) if side == SOURCE else None
        )
    context = {"query": query, "side": side, "results": results, "exceeded": exceeded}
    if request.GET.get("fragment"):
        return render(request, "translations/concordance_results.html", context)
    return render(request, "translations/concordance.html", context)


# Glossary of a project


@require_http_methods(["GET", "POST"])
def glossary(request, pk):
    """The terms of a project: adopted, then proposed; the form to propose one."""
    user = request.user
    project = _project(user, pk)
    can_propose = glossary_services.can_propose_term(user, project)
    form = GlossaryEntryForm(request.POST or None, user=user) if can_propose else None
    if request.method == "POST":
        if form is None:
            raise Http404
        if form.is_valid():
            entry = form.save()
            entry.project = project
            entry, saved = _contribute(request, glossary_services.propose_term, entry, user)
            if saved:
                if entry.is_adopted:
                    messages.success(request, _("Le terme entre dans le glossaire."))
                else:
                    messages.success(
                        request,
                        _("Le terme est proposé : le créateur du projet ou un relecteur décide."),
                    )
                return redirect("translations:glossary", project.pk)
    statuses = [GlossaryEntry.Status.ADOPTED, GlossaryEntry.Status.PROPOSED]
    if request.GET.get("ecartes"):
        statuses.append(GlossaryEntry.Status.REJECTED)
    entries = glossary_services.visible_terms(user, project, statuses)
    entries.sort(key=lambda entry: (not entry.is_adopted, entry.source_term.casefold()))
    for entry in entries:
        entry.can_change = glossary_services.can_change_term(user, entry)
    return render(
        request,
        "translations/glossary.html",
        {
            "project": project,
            "entries": entries,
            "form": form,
            "can_decide": glossary_services.can_decide_term(user, project),
            "show_rejected": bool(request.GET.get("ecartes")),
        },
    )


def _entry(user, project, entry_pk):
    entry = get_object_or_404(project.glossary.all(), pk=entry_pk)
    entry.project = project
    if not can_view(user, entry):
        raise Http404
    return entry


@login_required
@require_http_methods(["GET", "POST"])
def glossary_edit(request, pk, entry_pk):
    project = _project(request.user, pk)
    entry = _entry(request.user, project, entry_pk)
    if not glossary_services.can_change_term(request.user, entry):
        raise PermissionDenied
    form = GlossaryEntryForm(request.POST or None, instance=entry, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision, saved = _contribute(request, save_with_revision, form.save(), request.user)
        if saved:
            messages.success(
                request, _("Le terme est modifié.") if revision else _("Aucune modification.")
            )
            return redirect(entry)
    return render(
        request,
        "translations/glossary_form.html",
        {"project": project, "entry": entry, "form": form},
    )


@login_required
@require_POST
def glossary_decide(request, pk, entry_pk):
    project = _project(request.user, pk)
    entry = _entry(request.user, project, entry_pk)
    decision = request.POST.get("decision")
    if decision not in ("adopt", "reject"):
        return HttpResponseBadRequest()
    glossary_services.decide_term(entry, request.user, adopt=decision == "adopt")
    if decision == "adopt":
        messages.success(request, _("Le terme est adopté."))
    else:
        messages.success(request, _("Le terme est écarté."))
    return redirect(entry)


@require_GET
def glossary_export(request, pk, extension):
    """The adopted terms of a glossary as CSV or TBX (TermBase eXchange), for other software."""
    if extension not in ("csv", "tbx"):
        raise Http404
    project = _project(request.user, pk)
    entries = glossary_services.visible_terms(request.user, project)
    language = project.source_text.language
    filename = f"glossaire-{slugify(project.title) or project.pk}.{extension}"
    if extension == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([language, "la", "note"])
        for entry in entries:
            writer.writerow(
                [_csv_cell(entry.source_term), _csv_cell(entry.latin_term), _csv_cell(entry.note)]
            )
        content, content_type = output.getvalue(), "text/csv; charset=utf-8"
    else:
        content = render_to_string(
            "translations/glossary.tbx",
            {"project": project, "entries": entries, "language": language},
        )
        content_type = "application/x-tbx+xml; charset=utf-8"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _csv_cell(value):
    """A cell a spreadsheet will not run as a formula."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@") else value
