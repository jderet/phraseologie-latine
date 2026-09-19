import datetime as dt
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from activity.models import Event, Star
from activity.templatetags.activity_tags import star_counts
from corpus.forms import MODE_FORM, SCOPE_CORE, TERM_NUMBERS, SearchForm
from justifications.display import visible_evidences
from justifications.models import Challenge, Justification
from moderation.registry import can_view
from moderation.services import save_with_revision

from .diffs import word_diff
from .editor import panel_tabs, row_data
from .exports import bilingual_text, export_filename
from .forms import (
    ProjectForm,
    ProposalForm,
    PublishForm,
    ReferenceForm,
    SentenceEditForm,
    SentenceInsertForm,
    SentenceSplitForm,
    SourceProposalForm,
    SourceStateForm,
    SourceTextEditForm,
    SourceTextForm,
    StepForm,
    TranslationTextForm,
    VersionForm,
)
from .members import active_members
from .models import (
    ChangeProposal,
    ProposedSentence,
    SourceProposal,
    SourceText,
    TranslationProject,
    TranslationVersion,
    is_version_writer,
)
from .permissions import (
    can_challenge,
    can_change_source,
    can_copy,
    can_edit,
    can_manage,
    can_propose,
    can_propose_source,
    can_translate,
)
from .segmentation import from_lines, segment, to_lines
from .services import (
    add_proposal_operation,
    adopt_source_proposal,
    change_source_text,
    copy_version,
    create_project,
    create_proposal,
    create_source_text,
    create_step,
    create_version,
    decide_sentence,
    publish_version,
    rebase_source_proposal,
    refuse_source_proposal,
    save_translation,
    send_source_proposal,
    set_reference_version,
    undo_proposal_operation,
    withdraw_proposal,
    withdraw_source_proposal,
)
from .sources import Line, SourceHistory, describe_operations, simulate
from .steps import (
    carried,
    compare,
    latest_step,
    pending_changes,
    public_step,
    shown_sentences,
    step_history,
    step_sentences,
    waiting_justifications,
)

ITEMS_PER_PAGE = 50
# Value of the comparison parameter that designates the working text of the author.
WORKING_TEXT = "travail"
PANEL_SEARCH_DEFAULTS = {
    "scope": SCOPE_CORE,
    "distance": SearchForm.DEFAULT_DISTANCE,
    **{f"mode{number}": MODE_FORM for number in TERM_NUMBERS},
}


def _visible(user, queryset, pk):
    obj = get_object_or_404(queryset, pk=pk)
    if not can_view(user, obj):
        raise Http404
    return obj


def _paginate(request, queryset):
    return Paginator(queryset, ITEMS_PER_PAGE).get_page(request.GET.get("page"))


def _contribute(request, save, *args):
    """Run a saving service; a reached limit is shown as a message. Return (result, saved)."""
    try:
        return save(*args), True
    except ContributionLimitReached as error:
        messages.error(request, str(error))
        return None, False


def _saved_message(request, revision):
    if revision is None:
        messages.info(request, _("Aucune modification."))
    else:
        messages.success(request, _("Les modifications sont enregistrées."))


# Source texts


def source_list(request):
    texts = (
        SourceText.objects.filter(is_hidden=False)
        .select_related("added_by")
        .annotate(segment_count=Count("segments", filter=Q(segments__removed_in__isnull=True)))
        .order_by("-created_at", "-pk")
    )
    return render(request, "translations/source_list.html", {"page": _paginate(request, texts)})


def source_detail(request, pk):
    source = _visible(request.user, SourceText.objects.select_related("added_by"), pk)
    return render(
        request,
        "translations/source_detail.html",
        {
            "source": source,
            "segments": source.segments.current(),
            "projects": source.projects.filter(is_hidden=False).select_related("created_by"),
            "can_edit": can_edit(request.user, source),
            "can_change": can_change_source(request.user, source),
            "may_propose": can_propose_source(request.user, source),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_create(request):
    """Adding a text takes two steps: the text is split, then the split is checked and saved."""
    if request.method != "POST":
        form = SourceTextForm(user=request.user)
        return render(request, "translations/source_create.html", {"form": form})
    data = request.POST.copy()
    if data.get("segmented") != "1":
        data["text"] = to_lines(segment(data.get("text", ""), data.get("language", "")))
        form = SourceTextForm(data, user=request.user)
        return render(
            request,
            "translations/source_create.html",
            {"form": form, "segmented": True, "sentences": from_lines(data["text"])},
        )
    form = SourceTextForm(data, user=request.user)
    if form.is_valid():
        source, saved = _contribute(
            request, create_source_text, form.save(commit=False), request.user, form.sentences
        )
        if saved:
            messages.success(request, _("Le texte est ajouté."))
            return redirect(source)
    return render(
        request,
        "translations/source_create.html",
        {"form": form, "segmented": True, "sentences": from_lines(data.get("text", ""))},
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_edit(request, pk):
    source = _visible(request.user, SourceText.objects.all(), pk)
    if not can_edit(request.user, source):
        raise PermissionDenied
    form = SourceTextEditForm(request.POST or None, instance=source, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision, saved = _contribute(
            request, save_with_revision, form.save(commit=False), request.user
        )
        if saved:
            _saved_message(request, revision)
            return redirect(source)
    return render(request, "translations/source_edit.html", {"form": form, "source": source})


# Sentences of a source text


def _lines(sentences):
    return [Line(sentence.text, sentence.starts_paragraph) for sentence in sentences]


def _shown(lines, number):
    """A sentence of ``lines`` by its number, for the templates; 404 if there is none."""
    if not 1 <= number <= len(lines):
        raise Http404
    line = lines[number - 1]
    return {"order": number, "text": line.text, "starts_paragraph": line.starts_paragraph}


def _preparing_proposal(user, source):
    """The user's proposal in preparation for a text, if any."""
    if not user.is_authenticated:
        return None
    return SourceProposal.objects.filter(
        source_text=source, author=user, status=SourceProposal.Status.PREPARING
    ).first()


def source_sentences(request, pk):
    """The sentences of a text and its changes, with the actions to change it.

    Whoever may change the text changes it directly; any other active account prepares a
    proposal, whose changes the page shows already applied.
    """
    user = request.user
    source = _visible(user, SourceText.objects.all(), pk)
    can_change = can_change_source(user, source)
    may_propose = can_propose_source(user, source)
    lines = _lines(source.segments.current())
    proposal = _preparing_proposal(user, source) if may_propose else None
    prepared, stale = [], False
    if proposal is not None:
        stale = proposal.base_state != source.state
        base = SourceHistory(source).segments_at(proposal.base_state)
        prepared = describe_operations(_lines(base), proposal.operations)
        if not stale:
            lines = simulate(lines, proposal.operations)
    open_proposals = source.proposals.filter(status=SourceProposal.Status.OPEN, is_hidden=False)
    return render(
        request,
        "translations/source_sentences.html",
        {
            "source": source,
            "sentences": [_shown(lines, number) for number in range(1, len(lines) + 1)],
            "changes": source.changes.select_related("author", "adopted_by").order_by("-number"),
            "can_change": can_change,
            "may_propose": may_propose,
            "actions": can_change or (may_propose and not stale),
            "proposal": proposal,
            "prepared": prepared,
            "stale": stale,
            "send_form": SourceProposalForm(user=user) if prepared and not stale else None,
            "open_proposal_count": open_proposals.count(),
        },
    )


def _editing(user, pk):
    """(source, lines, state): the sentences the user changes, and the state they are at.

    Whoever may change the text changes its current sentences, at the state of the text; any
    other active account, those of their proposal in preparation, at its number of changes.
    """
    source = _visible(user, SourceText.objects.all(), pk)
    lines = _lines(source.segments.current())
    if can_change_source(user, source):
        return source, lines, source.state
    if not can_propose_source(user, source):
        raise PermissionDenied
    proposal = _preparing_proposal(user, source)
    if proposal is None:
        return source, lines, 0
    if proposal.base_state == source.state:
        lines = simulate(lines, proposal.operations)
    return source, lines, len(proposal.operations)


def _change_sentences(request, source, form, operation, anchor):
    """Apply a change from a valid form, or add it to the user's proposal.

    Return the redirection, or None with the errors on the form.
    """
    user = request.user
    proposing = not can_change_source(user, source)
    save = add_proposal_operation if proposing else change_source_text
    try:
        _result, saved = _contribute(
            request, save, source, operation, user, form.cleaned_data["state"]
        )
    except ValidationError as error:
        if error.code == "stale":
            # The form is shown again against the current text.
            form.data = form.data.copy()
            form.data["state"] = _editing(user, source.pk)[2]
        form.add_error(None, error)
        return None
    if not saved:
        return None
    if proposing:
        messages.success(
            request,
            _("Le changement est ajouté à votre proposition. Envoyez-la quand elle est prête."),
        )
    else:
        messages.success(
            request,
            _("Le texte est modifié. Chaque version l’intégrera à sa prochaine étape."),
        )
    return redirect(f"{reverse('translations:source_sentences', args=[source.pk])}#phrase-{anchor}")


def _sentence_form(request, source, form, **context):
    proposing = not can_change_source(request.user, source)
    return render(
        request,
        "translations/source_sentence_form.html",
        {"source": source, "form": form, "proposing": proposing, **context},
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_sentence_edit(request, pk, number):
    source, lines, state = _editing(request.user, pk)
    sentence = _shown(lines, number)
    initial = {
        "text": sentence["text"],
        "starts_paragraph": sentence["starts_paragraph"],
        "state": state,
    }
    form = SentenceEditForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        operation = {
            "kind": "edit",
            "index": number - 1,
            "text": form.cleaned_data["text"],
            "starts_paragraph": form.cleaned_data["starts_paragraph"],
            "expected": [sentence["text"]],
        }
        if response := _change_sentences(request, source, form, operation, number):
            return response
    return _sentence_form(
        request,
        source,
        form,
        heading=_("Modifier la phrase %(number)d") % {"number": number},
        intro=_(
            "La phrase est remplacée ; l’ancienne reste dans les étapes qui l’ont figée. Le latin "
            "déjà écrit reste attaché à la phrase."
        ),
        shown=[sentence],
        submit=_("Enregistrer la phrase"),
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_sentence_split(request, pk, number):
    source, lines, state = _editing(request.user, pk)
    sentence = _shown(lines, number)
    initial = {"parts": sentence["text"], "state": state}
    form = SentenceSplitForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        operation = {
            "kind": "split",
            "index": number - 1,
            "parts": form.cleaned_data["parts"],
            "expected": [sentence["text"]],
        }
        if response := _change_sentences(request, source, form, operation, number):
            return response
    return _sentence_form(
        request,
        source,
        form,
        heading=_("Scinder la phrase %(number)d") % {"number": number},
        intro=_(
            "Allez à la ligne là où la phrase doit être coupée. Les mots ne changent pas ; le "
            "latin déjà écrit reste sur la première partie."
        ),
        shown=[sentence],
        submit=_("Scinder la phrase"),
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_sentence_merge(request, pk, number):
    source, lines, state = _editing(request.user, pk)
    shown = [_shown(lines, number), _shown(lines, number + 1)]
    form = SourceStateForm(request.POST or None, user=request.user, initial={"state": state})
    if request.method == "POST" and form.is_valid():
        operation = {
            "kind": "merge",
            "index": number - 1,
            "expected": [sentence["text"] for sentence in shown],
        }
        if response := _change_sentences(request, source, form, operation, number):
            return response
    return _sentence_form(
        request,
        source,
        form,
        heading=_("Fusionner les phrases %(number)d et %(next)d")
        % {"number": number, "next": number + 1},
        intro=_(
            "Les deux phrases n’en font plus qu’une. Dans chaque version, leurs latins sont mis "
            "bout à bout."
        ),
        shown=shown,
        submit=_("Fusionner"),
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_sentence_insert(request, pk):
    """Adding sentences takes two steps, as adding a text: the split is checked, then saved.

    ``apres`` is the number of the sentence they follow; 0 adds them at the start.
    """
    source, lines, state = _editing(request.user, pk)
    count = len(lines)
    after = request.GET.get("apres", "")
    after = int(after) if after.isdigit() else count
    if after > count:
        raise Http404
    if after == 0:
        heading = _("Ajouter des phrases au début")
    elif after == count:
        heading = _("Ajouter des phrases à la fin")
    else:
        heading = _("Ajouter des phrases après la phrase %(number)d") % {"number": after}
    context = {
        "heading": heading,
        "shown": [_shown(lines, after)] if after else [],
        "intro": _(
            "Collez le texte : il sera découpé en phrases, que vous vérifierez avant d’enregistrer."
        ),
        "submit": _("Découper en phrases"),
    }
    if request.method != "POST":
        form = SentenceInsertForm(user=request.user, initial={"state": state})
        return _sentence_form(request, source, form, **context)
    data = request.POST.copy()
    context |= {
        "segmented": True,
        "intro": _(
            "Vérifiez le découpage : une phrase par ligne, une ligne vide entre deux paragraphes."
        ),
        "submit": _("Ajouter les phrases"),
    }
    if data.get("segmented") != "1":
        data["text"] = to_lines(segment(data.get("text", ""), source.language))
        form = SentenceInsertForm(data, user=request.user)
        return _sentence_form(request, source, form, **context)
    form = SentenceInsertForm(data, user=request.user)
    if form.is_valid():
        operation = {
            "kind": "insert",
            "before": after,
            "sentences": form.sentences,
            "expected": [lines[after - 1].text] if after else [],
        }
        if response := _change_sentences(request, source, form, operation, after + 1):
            return response
    return _sentence_form(request, source, form, **context)


# Proposals of changes to a source text


def _source_proposal(user, pk):
    queryset = SourceProposal.objects.select_related("source_text", "author", "decided_by")
    proposal = get_object_or_404(queryset, pk=pk)
    if not can_view(user, proposal.source_text) or not can_view(user, proposal):
        raise Http404
    return proposal


def source_proposal_list(request, pk):
    """The proposals sent for a text, open ones first."""
    user = request.user
    source = _visible(user, SourceText.objects.all(), pk)
    proposals = [
        proposal
        for proposal in source.proposals.filter(sent_at__isnull=False).select_related("author")
        if can_view(user, proposal)
    ]
    proposals.sort(key=lambda proposal: not proposal.is_open)
    return render(
        request,
        "translations/source_proposal_list.html",
        {
            "source": source,
            "proposals": proposals,
            "may_propose": can_propose_source(user, source),
        },
    )


def source_proposal_detail(request, pk):
    """The changes of a proposal, described on the text they start from.

    Whoever may change the text adopts or refuses them as a whole.
    """
    user = request.user
    proposal = _source_proposal(user, pk)
    source = proposal.source_text
    base = SourceHistory(source).segments_at(proposal.base_state)
    pending = proposal.is_preparing or proposal.is_open
    stale = pending and proposal.base_state != source.state
    is_author = user.pk == proposal.author_id
    can_decide = proposal.is_open and can_change_source(user, source)
    return render(
        request,
        "translations/source_proposal_detail.html",
        {
            "proposal": proposal,
            "source": source,
            "described": describe_operations(_lines(base), proposal.operations),
            "stale": stale,
            "can_adopt": can_decide and not stale,
            "can_refuse": can_decide,
            "can_withdraw": is_author and pending,
            "can_rebase": is_author and stale,
        },
    )


@login_required
@require_POST
def source_proposal_send(request, pk):
    proposal = _source_proposal(request.user, pk)
    form = SourceProposalForm(request.POST, user=request.user)
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, errors[0])
        return redirect("translations:source_sentences", proposal.source_text_id)
    try:
        send_source_proposal(proposal, request.user, form.cleaned_data["explanation"])
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect("translations:source_sentences", proposal.source_text_id)
    messages.success(request, _("La proposition est envoyée."))
    return redirect(proposal)


@login_required
@require_POST
def source_proposal_act(request, pk, action):
    """Adopt, refuse, withdraw or take up again a proposal, or undo its latest change."""
    proposal = _source_proposal(request.user, pk)
    actions = {
        "adopter": (adopt_source_proposal, _("La proposition est adoptée : le texte est modifié.")),
        "refuser": (refuse_source_proposal, _("La proposition est refusée.")),
        "retirer": (withdraw_source_proposal, _("La proposition est retirée.")),
        "reprendre": (rebase_source_proposal, _("La proposition est reprise sur le texte actuel.")),
        "annuler": (undo_proposal_operation, _("Le dernier changement est annulé.")),
    }
    if action not in actions:
        raise Http404
    act, message = actions[action]
    try:
        act(proposal, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, message)
    if proposal.is_preparing and action in ("annuler", "reprendre"):
        return redirect("translations:source_sentences", proposal.source_text_id)
    return redirect(proposal)


# Projects


# Orders of the list of projects: newest, most starred, latest public activity.
PROJECT_ORDERS = {
    "recents": ("-created_at", "-pk"),
    "etoiles": ("-star_count", "-created_at", "-pk"),
    "activite": (F("last_activity").desc(nulls_last=True), "-created_at", "-pk"),
}


def project_list(request):
    published = Q(versions__state=TranslationVersion.State.PUBLISHED, versions__is_hidden=False)
    order = request.GET.get("tri") if request.GET.get("tri") in PROJECT_ORDERS else "recents"
    stars = (
        Star.objects.filter(
            version__project=OuterRef("pk"),
            version__state=TranslationVersion.State.PUBLISHED,
            version__is_hidden=False,
        )
        .order_by()
        .values("version__project")
        .annotate(total=Count("pk"))
        .values("total")
    )
    last_event = (
        Event.objects.filter(project=OuterRef("pk"), is_public=True)
        .order_by("-created_at")
        .values("created_at")[:1]
    )
    projects = (
        TranslationProject.objects.filter(is_hidden=False, source_text__is_hidden=False)
        .select_related("source_text", "created_by")
        .annotate(
            published_count=Count("versions", filter=published, distinct=True),
            star_count=Coalesce(Subquery(stars), 0),
            last_activity=Subquery(last_event),
        )
        .order_by(*PROJECT_ORDERS[order])
    )
    return render(
        request,
        "translations/project_list.html",
        {"page": _paginate(request, projects), "order": order},
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_create(request, source_pk):
    source = get_object_or_404(SourceText, pk=source_pk, is_hidden=False)
    form = ProjectForm(request.POST or None, user=request.user, initial={"title": source.title})
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.source_text = source
        project, saved = _contribute(request, create_project, project, request.user)
        if saved:
            messages.success(request, _("Le projet est créé."))
            return redirect(project)
    return render(request, "translations/project_form.html", {"form": form, "source": source})


def project_detail(request, pk):
    project = _visible(
        request.user, TranslationProject.objects.select_related("source_text", "created_by"), pk
    )
    versions = list(
        project.versions.visible_to(request.user).select_related(
            "author", "copied_from__version__author"
        )
    )
    stars = star_counts(versions)
    for version in versions:
        _step, sentences = shown_sentences(request.user, version)
        version.translated_count = sum(1 for sentence in sentences.values() if sentence.text)
        version.star_count = stars.get(version.pk, 0)
    by_stars = request.GET.get("tri") == "etoiles"
    if by_stars:
        versions.sort(key=lambda version: -version.star_count)
    return render(
        request,
        "translations/project_detail.html",
        {
            "project": project,
            "source": project.source_text,
            "segment_count": project.source_text.segments.current().count(),
            "published": [version for version in versions if version.is_published],
            "drafts": [version for version in versions if version.is_draft],
            "can_edit": can_edit(request.user, project),
            "can_change_source": can_change_source(request.user, project.source_text),
            "can_propose_source": can_propose_source(request.user, project.source_text),
            "reference_id": project.reference_version_id,
            "is_creator": request.user.pk == project.created_by_id,
            "by_stars": by_stars,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_edit(request, pk):
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    if not can_edit(request.user, project):
        raise PermissionDenied
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision, saved = _contribute(
            request, save_with_revision, form.save(commit=False), request.user
        )
        if saved:
            _saved_message(request, revision)
            return redirect(project)
    return render(
        request,
        "translations/project_form.html",
        {"form": form, "source": project.source_text, "project": project},
    )


@login_required
@require_POST
def project_reference(request, pk):
    project = _visible(request.user, TranslationProject.objects.all(), pk)
    if request.user.pk != project.created_by_id:
        raise PermissionDenied
    form = ReferenceForm(request.POST, project=project)
    if not form.is_valid():
        messages.error(request, _("Choisissez une version publiée de ce projet."))
        return redirect(project)
    version = form.cleaned_data["version"]
    if set_reference_version(project, version, request.user) is None:
        messages.info(request, _("Aucune modification."))
    elif version is None:
        messages.success(request, _("Le projet n’a plus de version de référence."))
    else:
        messages.success(request, _("La version de référence est choisie."))
    return redirect(project)


def project_compare(request, pk):
    """The versions of a project aligned sentence by sentence, the reference version first.

    Each version shows its latest public step; the author's own versions, their working text.
    The Latin of a step is carried to the current source text.
    """
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    versions = sorted(
        project.versions.visible_to(request.user).select_related("author"),
        key=lambda version: (
            version.pk != project.reference_version_id,
            version.is_draft,
            version.published_at or version.created_at,
        ),
    )
    asked = {int(value) for value in request.GET.getlist("v") if value.isdigit()}
    shown = [version for version in versions if version.pk in asked] or versions
    history = SourceHistory(project.source_text)
    sentences, states = {}, {}
    for version in shown:
        step, found = shown_sentences(request.user, version)
        if step is not None:
            found = history.project(carried(found), step.source_state)
            states[version.pk] = step.source_state
        sentences[version.pk] = found
    rows = []
    for number, source_segment in enumerate(history.segments_at(), start=1):
        cells = []
        for version in shown:
            sentence = sentences[version.pk].get(source_segment.pk)
            state = states.get(version.pk)
            cells.append(
                {
                    "version": version,
                    "text": sentence.text if sentence else "",
                    # The step shown was made before this sentence entered the source text.
                    "older": state is not None and source_segment.added_in > state,
                }
            )
        rows.append({"segment": source_segment, "number": number, "cells": cells})
    return render(
        request,
        "translations/project_compare.html",
        {
            "project": project,
            "source": project.source_text,
            "versions": versions,
            "shown": shown,
            "rows": rows,
            "reference_id": project.reference_version_id,
        },
    )


# Versions


def _version(user, pk):
    queryset = TranslationVersion.objects.select_related(
        "project__source_text", "author", "copied_from__version__author"
    )
    return _visible(user, queryset, pk)


def _own_version(user, pk):
    """A version the user writes, as its author or a co-author."""
    version = _version(user, pk)
    if not can_translate(user, version):
        raise PermissionDenied
    return version


def _managed_version(user, pk):
    """A version the user authored: only its author publishes it or changes its settings."""
    version = _version(user, pk)
    if not can_manage(user, version):
        raise PermissionDenied
    return version


def _justifications_by_segment(user, version, texts, history, state, step=None):
    """Justifications the user may see, read against the Latin shown (``texts`` by segment).

    Each goes to the sentence that carries its Latin at the ``state`` of the source text.
    With a step, only those it or an earlier step brought out.
    """
    grouped = defaultdict(list)
    open_challenges = Challenge.objects.filter(status=Challenge.Status.OPEN, is_hidden=False)
    queryset = (
        Justification.objects.filter(translated_segment__version=version)
        .select_related("translated_segment")
        .prefetch_related(
            Prefetch("challenges", queryset=open_challenges, to_attr="open_challenges")
        )
    )
    if step is not None:
        queryset = queryset.filter(step__number__lte=step.number)
    for justification in queryset:
        translated = justification.translated_segment
        translated.version = version
        segment = history.resolve(translated.segment_id, state)
        if segment is None or not can_view(user, justification):
            continue
        justification.shown_text = texts.get(segment.pk, "")
        grouped[segment.pk].append(justification)
    return grouped


def _challenges_by_segment(user, version, history, state):
    grouped = defaultdict(list)
    if version.is_draft:
        return grouped
    queryset = Challenge.objects.filter(
        translated_segment__version=version, status=Challenge.Status.OPEN
    ).select_related("translated_segment")
    for challenge in queryset:
        challenge.translated_segment.version = version
        segment = history.resolve(challenge.translated_segment.segment_id, state)
        if segment is not None and can_view(user, challenge):
            grouped[segment.pk].append(challenge)
    return grouped


def _rows(user, version, step=None):
    """The step shown and each sentence of the source text with its Latin and justifications.

    Return (step, rows): the author sees the working text (step None), others the latest
    public step; a step asked shows its own text, with the source text it froze.
    """
    step, sentences = shown_sentences(user, version, step)
    history = SourceHistory(version.project.source_text)
    state = step.source_state if step else history.state
    texts = {segment_id: sentence.text for segment_id, sentence in sentences.items()}
    justifications = _justifications_by_segment(user, version, texts, history, state, step)
    challenges = _challenges_by_segment(user, version, history, state)
    translated_ids = dict(version.segments.values_list("segment_id", "pk"))
    # In their working text, the author sees the sentences the source text changed since.
    since = _source_changed_since(user, version) if step is None else None
    rows = []
    for number, source_segment in enumerate(history.segments_at(state), start=1):
        sentence = sentences.get(source_segment.pk)
        text = sentence.text if sentence else ""
        changed = since is not None and source_segment.added_in > since.source_state
        rows.append(
            {
                "segment": source_segment,
                "number": number,
                "translated_pk": translated_ids.get(source_segment.pk),
                "sentence": sentence,
                "saved": text,
                "text": text,
                "errors": None,
                "justifications": justifications.get(source_segment.pk, []),
                "challenges": challenges.get(source_segment.pk, []),
                "origin": _origin(user, version, sentence) if step and sentence else None,
                "source_changed": changed,
                "previous_sources": (
                    history.origins(source_segment, since.source_state) if changed else []
                ),
            }
        )
    return step, rows


def _source_changed_since(user, version):
    """The latest step of a version the user writes, if the source text has changed since."""
    if not is_version_writer(user, version):
        return None
    latest = latest_step(version)
    if latest is None or latest.source_state >= version.project.source_text.state:
        return None
    return latest


def _origin(user, version, sentence):
    """The step that last changed a frozen sentence, if the user may see it, and who wrote it."""
    changed_in = sentence.step
    changed_in.version = version
    return {
        "step": changed_in if can_view(user, changed_in) else None,
        "written_by": sentence.written_by,
    }


def _progress(rows):
    return {
        "translated_count": sum(1 for row in rows if row["saved"]),
        "segment_count": len(rows),
    }


def version_detail(request, pk):
    """The author sees the working text; others see the latest public step."""
    user = request.user
    version = _version(user, pk)
    step, rows = _rows(user, version)
    is_author = is_version_writer(user, version)
    copy_step = step or public_step(version)
    if copy_step is not None:
        copy_step.version = version
    return render(
        request,
        "translations/version_detail.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "rows": rows,
            "latest_step": latest_step(version) if is_author else step,
            "pending_count": len(pending_changes(version)) if is_author else 0,
            "source_step": _source_changed_since(user, version),
            "waiting_count": waiting_justifications(version).count() if is_author else 0,
            "is_author": is_author,
            "can_translate": can_translate(user, version),
            "can_manage": can_manage(user, version),
            "members": active_members(version),
            "is_reference": version.pk == version.project.reference_version_id,
            "can_challenge": step is not None and can_challenge(user, version),
            "copy_step": copy_step if copy_step and can_copy(user, copy_step) else None,
            "can_propose": step is not None and can_propose(user, version),
            "open_proposal_count": version.proposals.filter(
                status=ChangeProposal.Status.OPEN, is_hidden=False
            ).count(),
            **_progress(rows),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def version_create(request, project_pk):
    project = get_object_or_404(TranslationProject, pk=project_pk, is_hidden=False)
    form = VersionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        version = form.save(commit=False)
        version.project = project
        version, saved = _contribute(request, create_version, version, request.user)
        if saved:
            return redirect("translations:version_edit", version.pk)
    return render(request, "translations/version_form.html", {"form": form, "project": project})


@login_required
@require_http_methods(["GET", "POST"])
def version_edit(request, pk):
    version = _own_version(request.user, pk)
    _step, rows = _rows(request.user, version)
    for row in rows:
        row["data"] = row_data(row)
    if request.method == "POST":
        changes = []
        for row in rows:
            key = f"s{row['segment'].pk}"
            if key not in request.POST:
                continue
            row["text"] = request.POST[key]
            form = TranslationTextForm({"text": request.POST[key]}, user=request.user)
            if not form.is_valid():
                row["errors"] = form.errors["text"]
            elif form.cleaned_data["text"] != row["saved"]:
                changes.append((row["segment"], form.cleaned_data["text"]))
        if not any(row["errors"] for row in rows):
            with transaction.atomic():
                for source_segment, text in changes:
                    save_translation(version, source_segment, text, request.user)
            if changes:
                messages.success(
                    request,
                    ngettext(
                        "%(count)d phrase enregistrée.",
                        "%(count)d phrases enregistrées.",
                        len(changes),
                    )
                    % {"count": len(changes)},
                )
            if request.POST.get("next") == "step":
                return redirect("translations:step_create", version.pk)
            if not changes:
                messages.info(request, _("Aucune modification."))
            return redirect("translations:version_edit", version.pk)
        messages.error(request, _("Rien n’est enregistré : corrigez les phrases signalées."))
    return render(
        request,
        "translations/version_edit.html",
        {
            "search_form": SearchForm(initial=PANEL_SEARCH_DEFAULTS),
            "panel_tabs": panel_tabs(version),
            "has_members": active_members(version).exists(),
            "source_step": _source_changed_since(request.user, version),
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "rows": rows,
            **_progress(rows),
        },
    )


def _download(content, version, extension, content_type):
    response = HttpResponse(content, content_type=content_type)
    filename = export_filename(version, extension)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def version_export_text(request, pk):
    """The source text and the Latin of a version, sentence by sentence, as a text file."""
    version = _version(request.user, pk)
    step, rows = _rows(request.user, version)
    content = bilingual_text(version, rows, step)
    return _download(content, version, "txt", "text/plain; charset=utf-8")


def _export_context(request, version):
    """What the TEI and TMX exports show: the rows and, for TEI, the visible evidence."""
    step, rows = _rows(request.user, version)
    for row in rows:
        for justification in row["justifications"]:
            justification.evidence_list = visible_evidences(
                request.user, justification.evidences.all(), justification=justification
            )
    now = timezone.now()
    return {
        "version": version,
        "project": version.project,
        "source": version.project.source_text,
        "step": step,
        "rows": rows,
        "exported_at": now,
        "creation_date": now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ"),
        "version_url": request.build_absolute_uri(version.get_absolute_url()),
        "site_name": _("Phraséologie latine"),
    }


def version_export_tei(request, pk):
    """The version as a TEI document: source and Latin aligned, justifications as notes."""
    version = _version(request.user, pk)
    content = render_to_string("translations/version.tei.xml", _export_context(request, version))
    return _download(content, version, "tei.xml", "application/tei+xml; charset=utf-8")


def version_export_tmx(request, pk):
    """The version as a translation memory (TMX 1.4): one unit per translated sentence."""
    version = _version(request.user, pk)
    content = render_to_string("translations/version.tmx", _export_context(request, version))
    return _download(content, version, "tmx", "application/x-tmx+xml; charset=utf-8")


def version_export_print(request, pk):
    """A printable page with the justifications as notes; the browser saves it as PDF."""
    version = _version(request.user, pk)
    step, rows = _rows(request.user, version)
    notes = []
    corpus_sources = set()
    for row in rows:
        row["notes"] = row["justifications"]
        for justification in row["notes"]:
            notes.append(justification)
            justification.note_number = len(notes)
            justification.evidence_list = visible_evidences(
                request.user, justification.evidences.all(), justification=justification
            )
            for evidence in justification.evidence_list:
                if getattr(evidence, "quotation", None):
                    edition = evidence.quotation.token.passage.edition
                    corpus_sources.add((edition.source, edition.license))
    return render(
        request,
        "translations/version_print.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "step": step,
            "rows": rows,
            "notes": notes,
            "corpus_sources": sorted(corpus_sources),
            "exported_at": timezone.now(),
        },
    )


@login_required
@require_POST
def translation_save(request, pk, segment_pk):
    """Save the Latin of one sentence from the editor; the answer is JSON."""
    version = _own_version(request.user, pk)
    source_segment = get_object_or_404(
        version.project.source_text.segments.current(), pk=segment_pk
    )
    form = TranslationTextForm(request.POST, user=request.user)
    if not form.is_valid():
        errors = [error["message"] for error in form.errors["text"].get_json_data()]
        return JsonResponse({"errors": errors}, status=400)
    text = form.cleaned_data["text"]
    revision = save_translation(version, source_segment, text, request.user)
    return JsonResponse({"text": text, "changed": revision is not None})


@login_required
@require_http_methods(["GET", "POST"])
def version_settings(request, pk):
    version = _managed_version(request.user, pk)
    form = VersionForm(request.POST or None, instance=version, user=request.user)
    if request.method == "POST" and form.is_valid():
        _saved_message(request, save_with_revision(form.save(commit=False), request.user))
        return redirect(version)
    return render(
        request,
        "translations/version_form.html",
        {"form": form, "project": version.project, "version": version},
    )


@login_required
@require_http_methods(["GET", "POST"])
def version_publish(request, pk):
    version = _managed_version(request.user, pk)
    if version.is_published:
        messages.info(request, _("Cette version est déjà publiée."))
        return redirect(version)
    # Bound on every POST: both fields are optional, so the data may be empty.
    form = PublishForm(request.POST if request.method == "POST" else None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            publish_version(
                version,
                request.user,
                message=form.cleaned_data["message"],
                show_draft_steps=form.cleaned_data["show_draft_steps"],
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("La version est publiée."))
            return redirect(version)
    return render(
        request,
        "translations/version_publish.html",
        {
            "version": version,
            "project": version.project,
            "form": form,
            "draft_step_count": version.steps.count(),
            **_progress(_rows(request.user, version)[1]),
        },
    )


# Steps


def step_list(request, pk):
    """The steps of a version the user may see, the latest first, each with what it changed
    since the previous one: a summary, and the detail word by word."""
    user = request.user
    version = _version(user, pk)
    steps = [
        step
        for step in version.steps.order_by("number")
        if can_view(user, _with_version(step, version))
    ]
    entries = [
        {"step": step, "comparison": comparison}
        for step, comparison in reversed(step_history(version, steps))
    ]
    current = public_step(version)
    return render(
        request,
        "translations/step_list.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "steps": steps[::-1],
            "entries": entries,
            "current_id": current.pk if current else None,
            "can_translate": can_translate(user, version),
        },
    )


def step_detail(request, pk, number):
    """The text of a version as a step froze it, at a fixed address that can be cited."""
    user = request.user
    version = _version(user, pk)
    step = get_object_or_404(version.steps.select_related("author"), number=number)
    step.version = version
    if not can_view(user, step):
        raise Http404
    _step, rows = _rows(user, version, step)
    others = [
        other
        for other in version.steps.exclude(pk=step.pk).order_by("number")
        if can_view(user, _with_version(other, version))
    ]
    visible = [other.number for other in others]
    # What this step changed since the previous step the user may see.
    earlier = [other for other in others if other.number < step.number]
    _step, comparison = step_history(version, [*earlier, step])[-1]
    current = public_step(version)
    return render(
        request,
        "translations/step_detail.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "step": step,
            "rows": rows,
            "comparison": comparison,
            "previous_number": max((n for n in visible if n < step.number), default=None),
            "next_number": min((n for n in visible if n > step.number), default=None),
            "is_current": current is not None and current.pk == step.pk,
            "is_private": step.during_draft and not version.shows_draft_steps,
            "show_origin": True,
            "can_copy": can_copy(user, step),
            **_progress(rows),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def version_copy(request, pk, number):
    """Start one's own draft version from a public step of a published version."""
    source = _version(request.user, pk)
    step = get_object_or_404(source.steps, number=number)
    step.version = source
    if not can_copy(request.user, step):
        raise Http404
    form = VersionForm(
        request.POST or None,
        user=request.user,
        initial={"style": source.style, "style_note": source.style_note},
    )
    if request.method == "POST" and form.is_valid():
        version, saved = _contribute(
            request, copy_version, step, form.save(commit=False), request.user
        )
        if saved:
            messages.success(
                request, _("La copie est créée : c’est votre brouillon, visible de vous seul.")
            )
            return redirect("translations:version_edit", version.pk)
    return render(
        request,
        "translations/version_copy.html",
        {"form": form, "source": source, "step": step, "project": source.project},
    )


def step_compare(request, pk):
    """Word-by-word differences between two steps the user may see.

    By default, between the latest step and the one before it; the author may also compare
    a step with the working text.
    """
    user = request.user
    version = _version(user, pk)
    is_author = can_translate(user, version)
    steps = [
        step
        for step in version.steps.order_by("number")
        if can_view(user, _with_version(step, version))
    ]
    if not steps and not is_author:
        raise Http404
    by_number = {str(step.number): step for step in steps}
    wanted = request.GET.get("a", "")
    if wanted in by_number:
        target = by_number[wanted]
    elif (wanted == WORKING_TEXT and is_author) or not steps:
        target = None
    else:
        target = steps[-1]
    if "de" in request.GET:
        base = by_number.get(request.GET["de"])
    else:
        earlier = [step for step in steps if target is None or step.number < target.number]
        base = earlier[-1] if earlier else None
    if base is not None and target is not None and base.number > target.number:
        base, target = target, base

    history = SourceHistory(version.project.source_text)
    if target is None:
        after = {item.segment_id: item for item in version.segments.current()}
        comparison = _comparison(history, base, after, history.state)
    else:
        comparison = _comparison(history, base, _frozen_texts(target), target.source_state)
    return render(
        request,
        "translations/step_compare.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "steps": steps,
            "base": base,
            "target": target,
            "is_author": is_author,
            "working": WORKING_TEXT,
            "comparison": comparison,
            "rows": comparison.sentences,
        },
    )


# Proposals


@login_required
@require_http_methods(["GET", "POST"])
def proposal_create(request, pk):
    """Propose changes to the latest public step of the published version of someone else."""
    user = request.user
    version = _version(user, pk)
    step = public_step(version)
    if step is None:
        raise Http404
    if not can_propose(user, version):
        raise PermissionDenied
    frozen = _frozen_texts(step)
    history = SourceHistory(version.project.source_text)
    rows = [
        {
            "segment": source_segment,
            "number": number,
            "text": frozen[source_segment.pk].text if source_segment.pk in frozen else "",
            "errors": None,
        }
        for number, source_segment in enumerate(history.segments_at(step.source_state), start=1)
    ]
    form = ProposalForm(request.POST or None, user=user)
    if request.method == "POST":
        texts = {}
        for row in rows:
            key = f"s{row['segment'].pk}"
            if key not in request.POST:
                continue
            row["text"] = request.POST[key]
            text_form = TranslationTextForm({"text": request.POST[key]}, user=user)
            if text_form.is_valid():
                texts[row["segment"]] = text_form.cleaned_data["text"]
            else:
                row["errors"] = text_form.errors["text"]
        if form.is_valid() and not any(row["errors"] for row in rows):
            proposal = form.save(commit=False)
            proposal.version = version
            try:
                proposal, saved = _contribute(request, create_proposal, proposal, user, texts)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                if saved:
                    messages.success(request, _("La proposition est envoyée."))
                    return redirect(proposal)
    return render(
        request,
        "translations/proposal_create.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "step": step,
            "rows": rows,
            "form": form,
        },
    )


def _proposal(user, pk):
    queryset = ChangeProposal.objects.select_related(
        "version__project__source_text", "version__author", "author", "base_step"
    )
    proposal = get_object_or_404(queryset, pk=pk)
    if not can_view(user, proposal.version) or not can_view(user, proposal):
        raise Http404
    return proposal


def proposal_detail(request, pk):
    """The proposed sentences word by word; the author of the version decides on each."""
    user = request.user
    proposal = _proposal(user, pk)
    version = proposal.version
    can_decide = proposal.is_open and can_translate(user, version)
    # Only the author of the version sees their working text, to spot what changed since.
    working = (
        dict(version.segments.current().values_list("segment_id", "text")) if can_decide else {}
    )
    numbers = SourceHistory(version.project.source_text).numbers_at(proposal.base_step.source_state)
    sentences = []
    for proposed in proposal.sentences.select_related("segment"):
        proposed.proposal = proposal
        if not can_view(user, proposed):
            continue
        current = working.get(proposed.segment_id, "")
        undecided = can_decide and proposed.is_pending
        source_changed = proposed.segment.removed_in is not None
        sentences.append(
            {
                "proposed": proposed,
                "number": numbers.get(proposed.segment_id),
                "chunks": word_diff(proposed.base_text, proposed.text),
                "working": current,
                "source_changed": undecided and source_changed,
                "changed_since": undecided and not source_changed and current != proposed.base_text,
            }
        )
    return render(
        request,
        "translations/proposal_detail.html",
        {
            "proposal": proposal,
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "sentences": sentences,
            "can_decide": can_decide,
            "can_withdraw": proposal.is_open and user.pk == proposal.author_id,
        },
    )


def proposal_list(request, pk):
    """The proposals made to a version, open ones first."""
    user = request.user
    version = _version(user, pk)
    proposals = []
    queryset = version.proposals.select_related("author").annotate(
        sentence_count=Count("sentences")
    )
    for proposal in queryset:
        proposal.version = version
        if can_view(user, proposal):
            proposals.append(proposal)
    proposals.sort(key=lambda proposal: not proposal.is_open)
    step = public_step(version)
    return render(
        request,
        "translations/proposal_list.html",
        {
            "version": version,
            "project": version.project,
            "proposals": proposals,
            "can_propose": step is not None and can_propose(user, version),
        },
    )


@login_required
@require_POST
def proposed_sentence_decide(request, pk):
    """The author of the version accepts or refuses one proposed sentence."""
    proposed = get_object_or_404(ProposedSentence.objects.select_related("segment"), pk=pk)
    proposal = _proposal(request.user, proposed.proposal_id)
    decision = request.POST.get("decision")
    if decision not in ("accept", "refuse"):
        return HttpResponseBadRequest()
    accept = decision == "accept"
    try:
        decide_sentence(proposed, request.user, accept=accept)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if accept:
            messages.success(
                request, _("La phrase est acceptée : elle entre dans votre texte de travail.")
            )
        else:
            messages.success(request, _("La phrase est refusée."))
    return redirect(f"{proposal.get_absolute_url()}#proposee-{proposed.pk}")


@login_required
@require_POST
def proposal_withdraw(request, pk):
    proposal = _proposal(request.user, pk)
    try:
        withdraw_proposal(proposal, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La proposition est retirée."))
    return redirect(proposal)


def _frozen_texts(step):
    """{segment id: Carried} of the text a step froze; empty for no step."""
    return carried(step_sentences(step)) if step is not None else {}


def _comparison(history, base, after, state):
    """What changed from the text of ``base`` (a step, or None for no text) to ``after``, a
    text at ``state`` of the source text."""
    if base is None:
        return compare(history, {}, state, after, state)
    return compare(history, _frozen_texts(base), base.source_state, after, state)


def _with_version(step, version):
    step.version = version
    return step


@login_required
@require_http_methods(["GET", "POST"])
def step_create(request, pk):
    """What changed since the latest step, and the form to freeze it with a message."""
    version = _own_version(request.user, pk)
    form = StepForm(request.POST if request.method == "POST" else None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            step = create_step(version, request.user, form.cleaned_data["message"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("L’étape %(number)d est créée.") % {"number": step.number})
            return redirect(step)
    history = SourceHistory(version.project.source_text)
    latest = latest_step(version)
    working = {item.segment_id: item for item in version.segments.current()}
    comparison = _comparison(history, latest, working, history.state)
    return render(
        request,
        "translations/step_create.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "form": form,
            "comparison": comparison,
            "changes": comparison.sentences,
            "waiting": waiting_justifications(version).select_related(
                "translated_segment__segment"
            ),
            "latest": latest,
        },
    )
