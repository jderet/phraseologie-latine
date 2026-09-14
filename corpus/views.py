from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from .forms import MODE_FORM, SCOPE_CORE, TERM_NUMBERS, SearchForm, bound_search_form, search_query
from .models import URN_PREFIX, Author, Edition, ReferenceTranslation, Work
from .search import author_distribution, build_hits, corpus_version, default_layer

PASSAGES_PER_PAGE = 50
RESULTS_PER_PAGE = 50
PANEL_RESULTS = 20
MAX_HIGHLIGHTED = 100


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
    return render(
        request,
        "corpus/passage.html",
        {
            "work": edition.work,
            "edition": edition,
            "passage": passage,
            "tokens": list(passage.tokens.order_by("position")),
            "highlighted": _word_ids(request.GET.get("mots", "")),
            "translations": beside,
            "previous": neighbours.filter(order__lt=passage.order).order_by("-order").first(),
            "following": neighbours.filter(order__gt=passage.order).order_by("order").first(),
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
    return context


def search(request):
    return render(request, "corpus/search.html", search_context(request, RESULTS_PER_PAGE))


def search_fragment(request):
    """Search results without the page around them, for the panel of the translation editor."""
    context = search_context(request, PANEL_RESULTS)
    return render(request, "corpus/search_results.html", {**context, "panel": True})
