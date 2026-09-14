import re
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from accounts.roles import is_reviewer
from phraseology.models import Kind, UsageMark
from phraseology.reading import (
    STATUS_LABELS,
    assign_tracks,
    focused_unit,
    legend_kinds,
    page_attestations,
    page_occurrences,
    reading_filters,
    unit_neighbours,
    units_on_page,
    word_marks,
    word_occurrences,
)
from phraseology.sightings import page_sightings
from phraseology.suggestions import page_suggestions

from .corrections import correction_changes, current_analysis, propose_correction, review_correction
from .forms import (
    MODE_FORM,
    SCOPE_CORE,
    TERM_NUMBERS,
    CorrectionForm,
    SearchForm,
    bound_search_form,
    search_query,
)
from .models import (
    URN_PREFIX,
    AnalysisCorrection,
    Author,
    Edition,
    ReferenceTranslation,
    Token,
    Work,
)
from .reading import capitalized, division_label, reading_plan, reading_rows
from .search import author_distribution, build_hits, corpus_version, default_layer
from .timeouts import TimeLimit

PASSAGES_PER_PAGE = 50
RESULTS_PER_PAGE = 50
PANEL_RESULTS = 20
MAX_HIGHLIGHTED = 100
# Value of the translation choice that hides the translation.
TRANSLATION_HIDDEN = "non"


def index(request):
    works = Work.objects.filter(editions__is_current=True).distinct().order_by("cts_urn")
    authors = (
        Author.objects.filter(works__editions__is_current=True)
        .distinct()
        .prefetch_related(Prefetch("works", queryset=works))
    )
    return render(request, "corpus/index.html", {"authors": authors})


def _current_edition(work_id):
    return get_object_or_404(
        Edition.objects.select_related("work__author"),
        work__cts_urn=URN_PREFIX + work_id,
        is_current=True,
    )


def work_detail(request, work_id):
    edition = _current_edition(work_id)
    page = Paginator(edition.passages.all(), PASSAGES_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request, "corpus/work.html", {"work": edition.work, "edition": edition, "page": page}
    )


def _word_ids(value):
    ids = [int(part) for part in value.split(",") if part.isdigit()]
    return set(ids[:MAX_HIGHLIGHTED])


def passage_detail(request, work_id, reference):
    edition = _current_edition(work_id)
    passage = get_object_or_404(edition.passages, reference=reference)
    neighbours = edition.passages.only("reference", "order")
    translations = ReferenceTranslation.objects.filter(work=edition.work, is_current=True)
    beside = [
        (translation, part)
        for translation in translations
        if (part := translation.part_for(passage.reference)) is not None
    ]
    tokens = list(passage.tokens.order_by("position"))
    occurrences = page_occurrences(
        page_attestations(request.user, [passage], reading_filters(request)),
        {token.pk for token in tokens},
        {passage.pk: passage.reference},
    )
    return render(
        request,
        "corpus/passage.html",
        {
            "work": edition.work,
            "edition": edition,
            "passage": passage,
            "tokens": tokens,
            "highlighted": _word_ids(request.GET.get("mots", "")),
            "marks": word_marks(occurrences),
            "page_units": units_on_page(occurrences),
            "translations": beside,
            "previous": neighbours.filter(order__lt=passage.order).order_by("-order").first(),
            "following": neighbours.filter(order__gt=passage.order).order_by("order").first(),
        },
    )


def _reading_url(work_id, page, suffix="", anchor=""):
    if page.key:
        url = reverse("corpus:reading_part", args=[work_id, page.key])
    else:
        url = reverse("corpus:reading", args=[work_id])
    return f"{url}{suffix}{anchor}"


def _query(**params):
    """A query string of the parameters that have a value, in the order given."""
    kept = {name: value for name, value in params.items() if value not in (None, "")}
    return f"?{urlencode(kept)}" if kept else ""


def _typed_reference(value):
    """A reference as people type it: « 1, 12 » or « 1 12 » is read as 1.12."""
    return re.sub(r"[\s,;]+", ".", value.strip()).strip(".")


def _translation_choice(request, translations):
    """The translation shown beside the Latin, and the value that keeps the choice in links."""
    choice = request.GET.get("traduction", "")
    if translations and choice == TRANSLATION_HIDDEN:
        return None, TRANSLATION_HIDDEN
    chosen = next((item for item in translations if str(item.pk) == choice), None)
    if chosen is not None:
        return chosen, choice
    return (translations[0] if translations else None), ""


def _page_words(passages):
    """The words of the passages of a page, by passage."""
    words = (
        Token.objects.filter(passage__in=passages)
        .only("id", "passage_id", "position", "form", "before", "after")
        .order_by("position")
    )
    return {key: list(group) for key, group in groupby(words, key=lambda word: word.passage_id)}


def _contents(plan, page, work_id, suffix):
    """The entries of the table of contents: the first divisions, or else the pages."""
    if plan.divisions:
        return [
            {
                "label": capitalized(division_label(plan.scheme, 0, value)),
                "url": _reading_url(work_id, target, suffix, f"#p-{reference}"),
                "current": target == page,
            }
            for value, reference, order in plan.divisions
            for target in [plan.page_at(order)]
        ]
    if len(plan.pages) > 1:
        return [
            {
                "label": other.label(plan.scheme),
                "url": _reading_url(work_id, other, suffix),
                "current": other == page,
            }
            for other in plan.pages
        ]
    return []


def reading(request, work_id, part=None):
    """A work read from end to end, page by page, its phraseology underlined."""
    user = request.user
    edition = _current_edition(work_id)
    work = edition.work
    plan = reading_plan(edition)
    if not plan.pages:
        raise Http404
    translations = list(ReferenceTranslation.objects.filter(work=work, is_current=True))
    translation, choice = _translation_choice(request, translations)
    focus = focused_unit(user, request.GET.get("fiche"))
    annotating = request.GET.get("annoter") == "1" and user.is_authenticated and user.is_active
    # What the links of the page keep: the translation, the unit followed, the annotation mode.
    state = {
        "traduction": choice,
        "fiche": focus.pk if focus else "",
        "annoter": "1" if annotating else "",
    }
    suffix = _query(**state)
    goto = _typed_reference(request.GET.get("aller", ""))
    if goto:
        passage = (
            edition.passages.filter(Q(reference=goto) | Q(reference__startswith=f"{goto}."))
            .order_by("order")
            .first()
        )
        if passage is not None:
            target = plan.page_at(passage.order)
            return redirect(_reading_url(work_id, target, suffix, f"#p-{passage.reference}"))
    page = plan.pages[0] if part is None else plan.page(part)
    if page is None:
        raise Http404
    passages = list(edition.passages.filter(order__range=(page.start, page.end)).order_by("order"))
    tokens = _page_words(passages)
    parts = translation.parts_for([item.reference for item in passages]) if translation else {}
    filters = reading_filters(request)
    token_ids = {word.pk for words in tokens.values() for word in words}
    occurrences = page_occurrences(
        page_attestations(user, passages, filters, focus),
        token_ids,
        {passage.pk: passage.reference for passage in passages},
    )
    marked = occurrences
    if annotating:
        # Occurrences of known schemas not yet attested, to confirm, and the sightings of
        # readers, to attach to an entry, drawn with the attestations.
        suggestions = page_suggestions(user, passages, token_ids, default_layer())
        marked = [*occurrences, *suggestions, *page_sightings(passages, token_ids)]
        assign_tracks(marked)
    page_url = _reading_url(work_id, page)

    def link(**changes):
        """This page, its state changed."""
        return f"{page_url}{_query(**{**state, **changes})}"

    page_units = units_on_page(occurrences)
    for entry in page_units:
        entry["focus_url"] = link(fiche=entry["unit"].pk)
    neighbours = None
    if focus is not None:
        found = unit_neighbours(focus, edition, page, filters)
        neighbours = {"total": found["total"]}
        for name in ("previous", "following"):
            attestation = found[name]
            if attestation is not None:
                target = plan.page_at(attestation.passage.order)
                anchor = f"#p-{attestation.passage.reference}"
                neighbours[f"{name}_url"] = _reading_url(work_id, target, suffix, anchor)
    index = plan.pages.index(page)
    around = {
        name: {"url": _reading_url(work_id, other, suffix), "label": other.label(plan.scheme)}
        for name, other in (
            ("previous", plan.pages[index - 1] if index > 0 else None),
            ("following", plan.pages[index + 1] if index + 1 < len(plan.pages) else None),
        )
        if other is not None
    }
    return render(
        request,
        "corpus/reading.html",
        {
            "work": work,
            "work_url": work.get_absolute_url(),
            "edition": edition,
            "label": page.label(plan.scheme),
            "page_url": page_url,
            "rows": reading_rows(
                page, plan.scheme, passages, tokens, parts, verse=work.form == Work.Form.VERSE
            ),
            "marks": word_marks(marked),
            "page_units": page_units,
            "legend_kinds": legend_kinds(occurrences),
            "filters": filters,
            "status_choices": list(STATUS_LABELS.items()),
            "kind_choices": Kind.choices,
            "mark_choices": UsageMark.choices,
            "register_choices": Work.Register.choices,
            "reset_url": link(filtres="defaut"),
            "focus": focus,
            "neighbours": neighbours,
            "unfocus_url": link(fiche=""),
            "keep": [(name, value) for name, value in state.items() if value],
            "annotating": annotating,
            "can_annotate": user.is_authenticated and user.is_active,
            "annotate_url": link(annoter="" if annotating else "1"),
            "translation": translation,
            "translation_links": [
                {
                    "translation": item,
                    "url": link(traduction=item.pk),
                    "current": item == translation,
                }
                for item in translations
            ],
            "hide_url": link(traduction=TRANSLATION_HIDDEN),
            "contents": _contents(plan, page, work_id, suffix),
            "previous": around.get("previous"),
            "following": around.get("following"),
            "goto": request.GET.get("aller", ""),
            "goto_missing": bool(goto),
        },
    )


def search_context(request, per_page):
    if "term1" in request.GET:
        form = bound_search_form(request.GET)
    else:
        form = SearchForm(
            initial={
                "scope": SCOPE_CORE,
                "distance": SearchForm.DEFAULT_DISTANCE,
                **{f"mode{number}": MODE_FORM for number in TERM_NUMBERS},
            }
        )
    context = {"form": form, "version": corpus_version(), "searched": False}
    if form.is_bound and form.is_valid():
        terms, distance, ordered = form.terms, form.search_distance, form.cleaned_data["ordered"]
        layer = default_layer()
        hits = form.hits(layer)
        with TimeLimit() as limit:
            page = Paginator(hits, per_page).get_page(request.GET.get("page"))
            context.update(
                searched=True,
                page=page,
                hits=build_hits(page.object_list, terms, distance, ordered, layer),
                distribution=author_distribution(hits),
                core_only=form.core_only,
                # What a search that finds nothing needs to be recorded.
                query=search_query(request.GET),
                expression=" ".join(
                    form.cleaned_data[f"term{n}"]
                    for n in TERM_NUMBERS
                    if form.cleaned_data.get(f"term{n}")
                ),
            )
        context["too_broad"] = limit.exceeded
        if context.get("hits"):
            words = {word.pk for hit in context["hits"] for word in hit.words}
            occurrences = word_occurrences(request.user, words, reading_filters(request))
            context["marks"] = word_marks(occurrences)
    return context


def search(request):
    return render(request, "corpus/search.html", search_context(request, RESULTS_PER_PAGE))


def search_fragment(request):
    """Search results without the page around them, for the panel of the translation editor."""
    context = search_context(request, PANEL_RESULTS)
    return render(request, "corpus/search_results.html", {**context, "panel": True})


# Corrections of the analysis

CORRECTIONS_PER_PAGE = 50
CORRECTION_DECISIONS = {
    "valider": AnalysisCorrection.Status.VALIDATED,
    "rejeter": AnalysisCorrection.Status.REJECTED,
}


def _word_url(token):
    return f"{token.passage.get_absolute_url()}?mots={token.pk}#mot-{token.pk}"


@login_required
@require_http_methods(["GET", "POST"])
def correction_create(request, pk):
    """A reader proposes to correct the analysis of a word."""
    token = get_object_or_404(Token.objects.select_related("passage__edition__work__author"), pk=pk)
    asked = request.GET.get("partie", "0")
    part = int(asked) if asked.isdigit() else 0
    back = request.POST.get("next") or request.GET.get("retour") or ""
    if not url_has_allowed_host_and_scheme(
        back, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        back = _word_url(token)
    correction = AnalysisCorrection(token=token, part=part)
    form = CorrectionForm(request.POST or None, instance=correction, token=token)
    if request.method == "POST" and form.is_valid():
        try:
            propose_correction(form.save(commit=False), request.user)
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("La correction est proposée ; un relecteur l’examinera."))
            return redirect(back)
    return render(
        request,
        "corpus/correction_form.html",
        {"token": token, "analysis": current_analysis(token, part), "form": form, "back": back},
    )


def correction_list(request):
    """The corrections of the analysis, by status; reviewers validate or reject them."""
    status = request.GET.get("statut", "")
    if status not in AnalysisCorrection.Status.values:
        status = AnalysisCorrection.Status.PROPOSED
    corrections = AnalysisCorrection.objects.filter(status=status, is_hidden=False).select_related(
        "token__passage__edition__work__author", "head", "created_by", "reviewed_by"
    )
    page = Paginator(corrections, CORRECTIONS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "corpus/correction_list.html",
        {
            "page": page,
            "corrections": [
                {
                    "correction": correction,
                    "url": _word_url(correction.token),
                    "changes": correction_changes(correction),
                }
                for correction in page.object_list
            ],
            "status": status,
            "statuses": AnalysisCorrection.Status.choices,
            "is_reviewer": is_reviewer(request.user),
        },
    )


@login_required
@require_POST
def correction_review(request, pk):
    correction = get_object_or_404(AnalysisCorrection, pk=pk)
    status = CORRECTION_DECISIONS.get(request.POST.get("decision", ""))
    if status is None:
        return HttpResponseBadRequest()
    try:
        review_correction(correction, request.user, status)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if status == AnalysisCorrection.Status.VALIDATED:
            messages.success(request, _("La correction est validée : elle s’applique à l’analyse."))
        else:
            messages.success(request, _("La correction est rejetée."))
    return redirect(f"{reverse('corpus:corrections')}?statut={AnalysisCorrection.Status.PROPOSED}")
