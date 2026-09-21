import datetime as dt
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from activity.models import Event, Star
from corpus.forms import MODE_FORM, SCOPE_CORE, TERM_NUMBERS, SearchForm
from justifications.display import visible_evidences
from justifications.models import Challenge, Justification
from moderation.registry import can_view
from moderation.services import save_with_revision

from .classification import (
    GENRE_GROUPS,
    THEME_GROUPS,
    Genre,
    Theme,
    grouped_choices,
)
from .comments import can_comment_sentence, comments_for, open_counts
from .editor import filter_choices, filter_rows, panel_tabs, row_data, status_counts
from .exports import bilingual_text, export_filename
from .forms import (
    ProjectForm,
    PublishForm,
    SentenceEditForm,
    SentenceInsertForm,
    SentenceSplitForm,
    SourceProposalForm,
    SourceStateForm,
    SourceTextEditForm,
    SourceTextForm,
    StepForm,
    StepLabelForm,
    TranslationTextForm,
)
from .glossary import find_terms, marked_text, visible_terms
from .members import writing_members
from .models import (
    Segment,
    SourceProposal,
    SourceText,
    TranslationProject,
    TranslationVersion,
    is_editor,
    is_version_writer,
)
from .permissions import (
    can_challenge,
    can_change_source,
    can_edit,
    can_manage,
    can_propose_source,
    can_translate,
)
from .qa import check_rows, ignored_alerts
from .segmentation import from_lines, segment, to_lines, unsplit_lines
from .services import (
    add_proposal_operation,
    adopt_source_proposal,
    change_source_text,
    create_project,
    create_source_text,
    create_step,
    publish_version,
    rebase_source_proposal,
    refuse_source_proposal,
    save_translation,
    send_source_proposal,
    undo_proposal_operation,
    withdraw_source_proposal,
)
from .sources import (
    Line,
    SourceHistory,
    describe_operations,
    outline,
    preview_divisions,
    reading_blocks,
    simulate,
    under,
)
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
from .variants import (
    can_add_variant,
    can_decide_variant,
    can_edit_variant,
    variants_by_segment,
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


# Orders of the texts on the page « Traduction »: newest, latest public activity of a project,
# most stars on the published versions of their projects.
TEXT_ORDERS = {
    "recents": ("-created_at", "-pk"),
    "activite": (F("last_activity").desc(nulls_last=True), "-created_at", "-pk"),
    "etoiles": ("-star_count", "-created_at", "-pk"),
}


def _text_page(request, genre="", theme="", page_genre=None, page_theme=None):
    """The page « Traduction »: each text with its projects and the progress of their
    translation (choice of 19 September 2026), narrowed to a genre or a theme."""
    order = request.GET.get("tri") if request.GET.get("tri") in TEXT_ORDERS else "recents"
    last_event = (
        Event.objects.filter(project__source_text=OuterRef("pk"), is_public=True)
        .order_by("-created_at")
        .values("created_at")[:1]
    )
    stars = (
        Star.objects.filter(
            version__project__source_text=OuterRef("pk"),
            version__project__is_hidden=False,
            version__state=TranslationVersion.State.PUBLISHED,
            version__is_hidden=False,
        )
        .order_by()
        .values("version__project__source_text")
        .annotate(total=Count("pk"))
        .values("total")
    )
    texts = SourceText.objects.filter(is_hidden=False)
    if genre:
        texts = texts.filter(genres__contains=[genre])
    if theme:
        texts = texts.filter(themes__contains=[theme])
    texts = (
        texts.select_related("added_by")
        .annotate(
            segment_count=Count("segments", filter=Q(segments__removed_in__isnull=True)),
            last_activity=Subquery(last_event),
            star_count=Coalesce(Subquery(stars), 0),
        )
        .order_by(*TEXT_ORDERS[order])
    )
    page = _paginate(request, texts)
    projects = _project_summaries(
        request.user,
        TranslationProject.objects.filter(is_hidden=False, source_text__in=list(page)),
    )
    by_text = defaultdict(list)
    for project in projects:
        by_text[project.source_text_id].append(project)
    for text in page:
        text.project_list = by_text.get(text.pk, [])
    return render(
        request,
        "translations/source_list.html",
        {
            "page": page,
            "order": order,
            "genre": genre,
            "theme": theme,
            "genre_groups": grouped_choices(GENRE_GROUPS),
            "theme_groups": grouped_choices(THEME_GROUPS),
            "page_genre": page_genre,
            "page_theme": page_theme,
        },
    )


def source_list(request):
    """All the texts, filtered by a genre and a theme chosen in the menus."""
    genre = request.GET.get("genre", "")
    theme = request.GET.get("theme", "")
    return _text_page(
        request,
        genre=genre if genre in Genre.values else "",
        theme=theme if theme in Theme.values else "",
    )


def source_by_genre(request, code):
    """The texts of one genre, at an address one can share."""
    if code not in Genre.values:
        raise Http404
    return _text_page(request, genre=code, page_genre=Genre(code).label)


def source_by_theme(request, code):
    """The texts of one theme, at an address one can share."""
    if code not in Theme.values:
        raise Http404
    return _text_page(request, theme=code, page_theme=Theme(code).label)


def _project_summaries(user, projects):
    """Projects with the progress of their translation, as the user sees it."""
    projects = list(
        projects.select_related("main_version__author", "source_text").order_by("created_at", "pk")
    )
    counts = dict(
        Segment.objects.current()
        .filter(source_text__in={project.source_text_id for project in projects})
        .order_by()
        .values("source_text")
        .annotate(total=Count("pk"))
        .values_list("source_text", "total")
    )
    for project in projects:
        main = project.main_version
        project.segment_count = counts.get(project.source_text_id, 0)
        project.main_visible = main is not None and can_view(user, main)
        project.translated_count = 0
        if project.main_visible:
            main.project = project
            _step, sentences = shown_sentences(user, main)
            project.translated_count = sum(1 for sentence in sentences.values() if sentence.text)
        project.percent = (
            round(100 * project.translated_count / project.segment_count)
            if project.segment_count
            else 0
        )
    return projects


# A text longer than this opens on one division at a time.
DIVISION_AT_ONCE = 300


def source_detail(request, pk):
    source = _visible(request.user, SourceText.objects.select_related("added_by"), pk)
    segments = list(source.segments.current())
    divisions, places = outline(segments)
    chosen = request.GET.get("division", "")
    if chosen and not any(division.key == chosen for division in divisions):
        chosen = ""
    if not chosen and divisions and len(segments) > DIVISION_AT_ONCE:
        chosen = divisions[0].key
    return render(
        request,
        "translations/source_detail.html",
        {
            "source": source,
            "divisions": divisions,
            "chosen": chosen,
            "whole": not chosen,
            "count": sum(1 for segment in segments if not segment.level),
            "blocks": reading_blocks(under(segments, places, chosen), places),
            "projects": _project_summaries(request.user, source.projects.filter(is_hidden=False)),
            "can_edit": can_edit(request.user, source),
            "can_change": can_change_source(request.user, source),
            "may_propose": can_propose_source(request.user, source),
        },
    )


def _checking(data, form):
    """The second step: the split to check, and the lines that look like several sentences."""
    sentences = from_lines(data.get("text", ""))
    divisions, before = preview_divisions(sentences)
    return {
        "form": form,
        "segmented": True,
        "count": sum(1 for sentence in sentences if not sentence.level),
        "divisions": divisions,
        "before": before,
        # Not saved: it only lends the names of the levels to the outline shown.
        "source": SourceText(level_names=data.get("level_names", "")),
        "unsplit": unsplit_lines(sentences, data.get("language", "")),
    }


@login_required
@require_http_methods(["GET", "POST"])
def source_create(request):
    """Adding a text takes two steps: the text is split, then the split is checked and saved."""
    if request.method != "POST":
        form = SourceTextForm(user=request.user)
        return render(request, "translations/source_create.html", {"form": form})
    data = request.POST.copy()
    if data.get("segmented") != "1" or data.get("resplit"):
        data["text"] = to_lines(segment(data.get("text", ""), data.get("language", "")))
        form = SourceTextForm(data, user=request.user)
        return render(request, "translations/source_create.html", _checking(data, form))
    form = SourceTextForm(data, user=request.user)
    if form.is_valid():
        context = _checking(data, form)
        if context["unsplit"] and not data.get("keep"):
            # A text pasted here was never split: the page says so before anything is saved.
            return render(request, "translations/source_create.html", context)
        source, saved = _contribute(
            request, create_source_text, form.save(commit=False), request.user, form.sentences
        )
        if saved:
            messages.success(request, _("Le texte est ajouté."))
            return redirect(source)
    return render(request, "translations/source_create.html", _checking(data, form))


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
    return [
        Line(sentence.text, sentence.starts_paragraph, sentence.level) for sentence in sentences
    ]


def _shown(lines, number):
    """A sentence of ``lines`` by its number, for the templates; 404 if there is none."""
    if not 1 <= number <= len(lines):
        raise Http404
    line = lines[number - 1]
    return {
        "order": number,
        "text": line.text,
        "starts_paragraph": line.starts_paragraph,
        "level": line.level,
    }


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


def project_list(request):
    """The projects are shown with their text, on the page « Traduction »."""
    return redirect("translations:source_list", permanent=True)


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
            messages.success(
                request,
                _("Le projet est créé : sa traduction reste un brouillon jusqu’à sa publication."),
            )
            return redirect("translations:version_edit", project.main_version.pk)
    return render(request, "translations/project_form.html", {"form": form, "source": source})


def project_detail(request, pk):
    """The translation of the project and the people who write it."""
    user = request.user
    project = _visible(
        user, TranslationProject.objects.select_related("source_text", "created_by"), pk
    )
    [summary] = _project_summaries(user, TranslationProject.objects.filter(pk=project.pk))
    main = summary.main_version if summary.main_visible else None
    return render(
        request,
        "translations/project_detail.html",
        {
            "project": project,
            "source": project.source_text,
            "summary": summary,
            "main": main,
            "writers": [project.created_by, *(m.user for m in writing_members(project))],
            "segment_count": summary.segment_count,
            "can_translate_main": main is not None and can_translate(user, main),
            "can_publish_main": main is not None and main.is_draft and can_manage(user, main),
            "is_editor": is_editor(user, project),
            "can_edit": can_edit(user, project),
            "can_change_source": can_change_source(user, project.source_text),
            "can_propose_source": can_propose_source(user, project.source_text),
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


def project_compare(request, pk):
    """The translations of the projects on the same source text, aligned sentence by sentence.

    Each translation shows its latest public step; its own writers see their working text. The
    variants of each sentence are shown on demand (choice of 21 September 2026).
    """
    user = request.user
    project = _visible(user, TranslationProject.objects.select_related("source_text"), pk)
    versions = sorted(
        TranslationVersion.objects.filter(project__source_text_id=project.source_text_id)
        .visible_to(user)
        .select_related("project", "author"),
        key=lambda version: (
            version.project_id != project.pk,
            version.is_draft,
            version.published_at or version.created_at,
        ),
    )
    asked = {int(value) for value in request.GET.getlist("p") if value.isdigit()}
    shown = [version for version in versions if version.project_id in asked] or versions
    with_variants = request.GET.get("variantes") == "1"
    history = SourceHistory(project.source_text)
    sentences, states, variants = {}, {}, {}
    for version in shown:
        step, found = shown_sentences(user, version)
        if step is not None:
            found = history.project(carried(found), step.source_state)
            states[version.pk] = step.source_state
        sentences[version.pk] = found
        variants[version.pk] = variants_by_segment(user, version) if with_variants else {}
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
                    "variants": variants[version.pk].get(source_segment.pk, []),
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
            "shown_ids": {version.project_id for version in shown},
            "with_variants": with_variants,
            "rows": rows,
            "main_id": project.main_version_id,
        },
    )


# Versions


def _version(user, pk):
    queryset = TranslationVersion.objects.select_related("project__source_text", "author")
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


def _rows(user, version, step=None, with_variants=False):
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
    variants = _variants_shown(user, version) if with_variants else {}
    # In their working text, the author sees the sentences the source text changed since.
    since = _source_changed_since(user, version) if step is None else None
    source = version.project.source_text
    divisions, places = history.outline_at(state)
    rows = []
    for number, source_segment in enumerate(history.segments_at(state), start=1):
        sentence = sentences.get(source_segment.pk)
        text = sentence.text if sentence else ""
        changed = since is not None and source_segment.added_in > since.source_state
        place = places[source_segment.pk]
        rows.append(
            {
                "segment": source_segment,
                # The number in the whole text: addresses, anchors and history use it.
                "number": number,
                # What is shown: the number inside the division, and where it stands.
                "place": place,
                "shown_number": place.number,
                "division": place.division,
                "citation": source.citation(place),
                "translated_pk": translated_ids.get(source_segment.pk),
                "sentence": sentence,
                "saved": text,
                "text": text,
                "errors": None,
                "justifications": justifications.get(source_segment.pk, []),
                "variants": variants.get(source_segment.pk, []),
                "challenges": challenges.get(source_segment.pk, []),
                "origin": _origin(user, version, sentence) if step and sentence else None,
                "source_changed": changed,
                "previous_sources": (
                    history.origins(source_segment, since.source_state) if changed else []
                ),
            }
        )
    return step, rows


def _variants_shown(user, version):
    """{segment id: [variant]} with, on each variant, what the user may do with it."""
    found = variants_by_segment(user, version)
    correcting = can_add_variant(user, version)
    for variants in found.values():
        for variant in variants:
            variant.can_decide = can_decide_variant(user, variant)
            variant.can_edit = can_edit_variant(user, variant)
            variant.can_correct = correcting
    return found


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
    """The progress of a version; the titles of divisions are not counted."""
    sentences = [row for row in rows if not row["segment"].level]
    return {
        "translated_count": sum(1 for row in sentences if row["saved"]),
        "segment_count": len(sentences),
    }


def version_detail(request, pk):
    """The author sees the working text; others see the latest public step."""
    user = request.user
    version = _version(user, pk)
    step, rows = _rows(user, version, with_variants=True)
    is_author = is_version_writer(user, version)
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
            "can_comment_sentences": step is not None and can_comment_sentence(user, version),
            "editions": [
                edition
                for edition in version.steps.exclude(label="").order_by("-number")
                if can_view(user, _with_version(edition, version))
            ],
            "members": writing_members(version.project),
            "can_challenge": step is not None and can_challenge(user, version),
            "can_add_variant": can_add_variant(user, version),
            **_progress(rows),
        },
    )


def version_create(request, project_pk):
    """A project has one translation, created with it."""
    project = get_object_or_404(TranslationProject, pk=project_pk, is_hidden=False)
    return redirect(project)


@login_required
@require_http_methods(["GET", "POST"])
def version_edit(request, pk):
    version = _own_version(request.user, pk)
    _step, rows = _rows(request.user, version)
    terms = visible_terms(request.user, version.project)
    open_comments = open_counts(request.user, version)
    alerts = check_rows(rows, terms, ignored_alerts(version))
    for row in rows:
        row["open_comments"] = open_comments.get(row["segment"].pk, 0)
        row["alerts"] = alerts.get(row["segment"].pk, [])
        row["data"] = row_data(row)
        if terms and find_terms(row["segment"].text, terms):
            row["source_marked"] = marked_text(row["segment"].text, terms)
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
    active_filter = request.GET.get("filtre", "")
    query = request.GET.get("q", "")[:200]
    divisions = [row["division"] for row in rows if row["segment"].level]
    chosen = request.GET.get("division", "")
    if chosen and not any(division.key == chosen for division in divisions):
        chosen = ""
    if not chosen and divisions and len(rows) > DIVISION_AT_ONCE:
        chosen = divisions[0].key
    shown = filter_rows(rows, active_filter, query, chosen)
    return render(
        request,
        "translations/version_edit.html",
        {
            "search_form": SearchForm(initial=PANEL_SEARCH_DEFAULTS),
            "panel_tabs": panel_tabs(version),
            "status_counts": status_counts(rows),
            "shown_rows": shown,
            "filters": filter_choices(),
            "active_filter": active_filter,
            "divisions": divisions,
            "chosen": chosen,
            "query": query,
            "has_members": writing_members(version.project).exists(),
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


def _export_step(request, version):
    """The step asked by ``?etape=N`` if the user may see it; None for the default text."""
    number = request.GET.get("etape", "")
    if not number.isdigit():
        return None
    step = get_object_or_404(version.steps, number=int(number))
    step.version = version
    if not can_view(request.user, step):
        raise Http404
    return step


def version_export_text(request, pk):
    """The source text and the Latin of a version, sentence by sentence, as a text file."""
    version = _version(request.user, pk)
    step, rows = _rows(request.user, version, _export_step(request, version))
    content = bilingual_text(version, rows, step)
    return _download(content, version, "txt", "text/plain; charset=utf-8")


def _export_context(request, version):
    """What the TEI and TMX exports show: the rows and, for TEI, the visible evidence."""
    step, rows = _rows(request.user, version, _export_step(request, version))
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


# States of XLIFF 1.2 for the statuses of the working text.
XLIFF_STATES = {
    "todo": "needs-translation",
    "draft": "needs-review-translation",
    "translated": "translated",
    "reviewed": "signed-off",
}


def version_export_xliff(request, pk):
    """The version as XLIFF 1.2, for translation software: the working text with its statuses
    for its writers, the latest public step for the others; comments as notes."""
    version = _version(request.user, pk)
    context = _export_context(request, version)
    comments = defaultdict(list)
    for comment in comments_for(request.user, version):
        if not comment.is_resolved:
            comments[comment.segment_id].append(comment)
    for row in context["rows"]:
        if context["step"] is None:
            status = row["sentence"].status if row["saved"] and row["sentence"] else "todo"
            row["xliff_state"] = XLIFF_STATES.get(status, "")
        else:
            row["xliff_state"] = "final" if row["saved"] else ""
        row["xliff_notes"] = comments.get(row["segment"].pk, [])
    context["exported_iso"] = (
        context["exported_at"].astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    content = render_to_string("translations/version.xlf", context)
    return _download(content, version, "xlf", "application/x-xliff+xml; charset=utf-8")


def version_export_print(request, pk):
    """A printable page with the justifications as notes; the browser saves it as PDF."""
    version = _version(request.user, pk)
    step, rows = _rows(request.user, version, _export_step(request, version))
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
    translated = version.segments.filter(segment=source_segment).first()
    status = translated.status if translated and translated.text else "todo"
    return JsonResponse({"text": text, "changed": revision is not None, "status": status})


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
            "can_label": can_translate(user, version),
            "label_form": StepLabelForm(instance=step, user=user),
            **_progress(rows),
        },
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
