from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.limits import ContributionLimitReached, is_limited
from accounts.roles import is_reviewer
from corpus.forms import search_query
from corpus.models import Author, Passage, Token, TokenAnalysis, Work
from corpus.search import corpus_version, default_layer, quotation
from corpus.text import normalize
from corpus.timeouts import TimeLimit
from corpus.views import lemma_search_initial, search_context
from justifications.display import visible_evidences
from justifications.forms import ReferenceFormSet
from justifications.models import Evidence
from justifications.services import corpus_evidence
from moderation.registry import can_view
from translations.models import TranslatedSegment, TranslationVersion
from translations.permissions import can_translate
from translations.steps import shown_text

from .abstract import rule_condition, rule_label
from .annotation import guess_schema, search_units, suggested_units
from .collocations import profile, profile_computed
from .completeness import (
    attestation_counts,
    mark_reviewed,
    passages_to_review,
    withdraw_review,
    work_progress,
)
from .composition import components, containers, schema_parts
from .dashboards import annotator_summary, public_figures, reviewer_queue
from .forms import (
    AbstractWordForm,
    AnnotationForm,
    AttestationPlaceForm,
    AttestationResolveForm,
    CandidateUnitForm,
    ContestForm,
    DoubtForm,
    EquivalentForm,
    NegativeSearchForm,
    NeologismCreateForm,
    NeologismEquivalentForm,
    NeologismForm,
    ReadingNoteForm,
    RealizationForm,
    RelationForm,
    ResolveContestForm,
    SchemaSearchForm,
    SenseForm,
    SightingForm,
    UnitCreateForm,
    UnitForm,
    UnitReferenceForm,
)
from .frequency import count_by_author, load_tokens, occurrence_words, schema_matches, slot_fillers
from .models import (
    AbstractWord,
    Attestation,
    AttestationDoubt,
    Candidate,
    Collocation,
    Equivalent,
    Kind,
    NegativeSearch,
    Neologism,
    NeologismEquivalent,
    Realization,
    Sense,
    Sighting,
    Unit,
    UnitFrequency,
    UnitReference,
    UnitRelation,
    UnitSurvey,
)
from .panel import unit_card, word_analysis, word_attestations
from .permissions import (
    can_edit_abstract_word,
    can_edit_neologism,
    can_edit_unit,
    can_withdraw_attestation,
)
from .reading_notes import create_reading_note, word_reading_notes
from .schema import SLOT, format_schema, parse_schema, schema_lemmas
from .schema_help import (
    abstract_words,
    check_schema,
    form_help,
    unit_schemas,
    word_choices,
)
from .search_terms import marked_search
from .services import (
    FREQUENCY_SECONDS,
    FrequencyTooLong,
    add_attestations,
    add_neologism_evidences,
    contest_attestation,
    contest_unit,
    create_abstract_word,
    create_neologism,
    create_unit,
    create_unit_from_candidate,
    current_frequency,
    decide_doubts,
    doubt_attestation,
    is_current,
    missing_fields,
    propose_unit,
    record_negative_search,
    recorded_search_form,
    refresh_frequency,
    reject_candidate,
    reopen_candidate,
    resolve_attestation_contest,
    resolve_contest,
    retain_candidate,
    review_attestation,
    review_attestations,
    save_neologism_equivalent,
    save_part,
    set_example,
    survey_unit,
    update_abstract_word,
    update_neologism,
    update_unit,
    validate_abstract_word,
    validate_neologism,
    validate_unit,
    withdraw_attestation,
    withdraw_neologism_equivalent,
    withdraw_neologism_evidence,
    withdraw_part,
)
from .sightings import (
    attestation_for,
    close_sighting,
    create_sighting,
    dismiss_sighting,
    open_sighting,
    sighting_words,
)
from .spotting import spot_units, visible_units
from .suggestions import confirm_suggestion
from .survey import attestation_shapes

UNITS_PER_PAGE = 50
SEARCH_RESULTS = 20
OCCURRENCES_PER_PAGE = 20
ATTESTATIONS_ON_UNIT_PAGE = 30
UNIT_FORM_ID = "unit-form"

# The parts of a unit edited by the same views: model, form, titles to add and to change.
PARTS = {
    "sens": (Sense, SenseForm, gettext_lazy("Ajouter un sens"), gettext_lazy("Modifier le sens")),
    "equivalents": (
        Equivalent,
        EquivalentForm,
        gettext_lazy("Ajouter un équivalent"),
        gettext_lazy("Modifier l’équivalent"),
    ),
    "realisations": (
        Realization,
        RealizationForm,
        gettext_lazy("Ajouter une réalisation"),
        gettext_lazy("Modifier la réalisation"),
    ),
    "relations": (
        UnitRelation,
        RelationForm,
        gettext_lazy("Ajouter une relation"),
        gettext_lazy("Modifier la relation"),
    ),
    "renvois": (
        UnitReference,
        UnitReferenceForm,
        gettext_lazy("Ajouter un renvoi bibliographique"),
        gettext_lazy("Modifier le renvoi bibliographique"),
    ),
}

DECISIONS = {"valider": Attestation.Status.VALIDATED, "rejeter": Attestation.Status.REJECTED}


def _unit(user, pk):
    unit = get_object_or_404(Unit.objects.select_related("created_by", "validated_by"), pk=pk)
    if not can_view(user, unit):
        raise Http404
    return unit


def _editable_unit(user, pk):
    unit = _unit(user, pk)
    if not can_edit_unit(user, unit):
        raise PermissionDenied
    return unit


def _part_type(kind):
    try:
        return PARTS[kind]
    except KeyError as error:
        raise Http404 from error


def _chosen_attestations(request, name="attestation"):
    """Attestations ticked in the form, and the errors of those that are not valid."""
    evidences, errors = [], []
    if request.method != "POST":
        return evidences, errors
    for value in dict.fromkeys(request.POST.getlist(name)):
        try:
            evidences.append(corpus_evidence(value))
        except ValidationError as error:
            errors.extend(error.messages)
    return evidences, errors


def _search_page(request, evidences, terms=None, **extra):
    """The corpus search of the page, and the attestations already ticked."""
    search = search_context(request, SEARCH_RESULTS, initial=lemma_search_initial(terms))
    found = {hit.word_ids for hit in search.get("hits", [])}
    chosen = [quotation(evidence.tokens) for evidence in evidences]
    return {
        "search": search,
        "chosen": [quote for quote in chosen if quote.word_ids not in found],
        "chosen_ids": {quote.word_ids for quote in chosen},
        "form_id": UNIT_FORM_ID,
        "attesting": True,
        **extra,
    }


def unit_list(request):
    units = Unit.objects.exclude(status=Unit.Status.DRAFT).filter(is_hidden=False)
    query = " ".join(request.GET.get("q", "").split())[:100]
    if query:
        units = units.filter(
            Q(reference_form__icontains=query) | Q(schema__icontains=normalize(query))
        )
    kind = request.GET.get("type", "")
    if kind in Kind.values:
        units = units.filter(kind=kind)
    status = request.GET.get("statut", "")
    if status in Unit.Status.values and status != Unit.Status.DRAFT:
        units = units.filter(status=status)
    tag = request.GET.get("etiquette", "").strip().lower()[:40]
    if tag:
        units = units.filter(tags__contains=[tag])
    drafts = []
    if request.user.is_authenticated:
        drafts = request.user.units.filter(status=Unit.Status.DRAFT)
    page = Paginator(units, UNITS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "phraseology/unit_list.html",
        {
            "page": page,
            "drafts": drafts,
            "query": query,
            "kind": kind,
            "status": status,
            "tag": tag,
            "kinds": Kind.choices,
            "statuses": [choice for choice in Unit.Status.choices if choice[0] != "draft"],
        },
    )


FREQUENCY_LATER = gettext_lazy(
    "Le nombre d’occurrences de ce schéma est trop long à compter maintenant : "
    "il sera compté plus tard."
)


@login_required
@require_http_methods(["GET", "POST"])
def unit_create(request):
    form = UnitCreateForm(
        request.POST or None,
        user=request.user,
        initial={
            "reference_form": request.GET.get("forme", ""),
            "schema": request.GET.get("schema", ""),
            "definition": request.GET.get("sens", ""),
        },
    )
    # The sense comes after the search of attestations, outside the form it belongs to.
    form.fields["definition"].widget.attrs["form"] = UNIT_FORM_ID
    evidences, errors = _chosen_attestations(request)
    if request.method == "GET" and request.GET.get("mots"):
        # Words chosen in the text being read come ticked.
        try:
            evidences = [corpus_evidence(request.GET["mots"])]
        except ValidationError:
            evidences = []
    if request.method == "POST":
        valid = form.is_valid()
        for message in errors:
            form.add_error(None, message)
        if valid and not errors:
            unit = form.save(commit=False)
            try:
                create_unit(unit, request.user, form.cleaned_data["definition"], evidences)
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                form.add_error(None, error)
            else:
                if unit.schema:
                    try:
                        refresh_frequency(unit, FREQUENCY_SECONDS)
                    except FrequencyTooLong:
                        messages.info(request, FREQUENCY_LATER)
                # An entry made from a sighting closes the sighting, if its words are ticked.
                sighting = open_sighting(request.POST.get("reperage"))
                if sighting is not None:
                    words = sighting_words(sighting)
                    close_sighting(sighting, attestation_for(unit, words), request.user)
                messages.success(
                    request, _("La fiche est créée : c’est un brouillon visible de vous seul.")
                )
                return redirect(unit)
    keep = {
        key: request.GET[key] for key in ("forme", "mots", "schema", "sens") if request.GET.get(key)
    }
    terms = marked_search(request.user, request.GET.get("forme", ""), request.GET.get("schema", ""))
    # The constructions come from the reference form: no field adds one by its name.
    context = _search_page(
        request, evidences, terms=terms, form=form, keep=keep, constructions_from_form=True
    )
    return render(request, "phraseology/unit_create.html", context)


def _visible_parts(user, unit, queryset):
    parts = []
    for part in queryset:
        if isinstance(part, Equivalent):
            part.sense.unit = unit
        else:
            part.unit = unit
        if can_view(user, part):
            parts.append(part)
    return parts


def _to_review(unit):
    """Attestations of the core found by a survey and not yet reviewed."""
    return unit.attestations.active().filter(
        is_hidden=False,
        level=Attestation.Level.AUTOMATIC,
        status=Attestation.Status.PROPOSED,
        passage__edition__work__is_core=True,
    )


def _outside_automatic(unit):
    """Attestations found automatically outside the core, shown as such on the survey page."""
    return (
        unit.attestations.active()
        .filter(level=Attestation.Level.AUTOMATIC)
        .exclude(passage__edition__work__is_core=True)
    )


def _attestations_of(user, unit):
    """Attestations shown on the unit page, examples first; the survey page shows the others.

    Returns the attestations and how many more there are.
    """
    tokens = Token.objects.select_related("passage__edition__work__author")
    queryset = (
        unit.attestations.active()
        .exclude(pk__in=_to_review(unit))
        .exclude(pk__in=_outside_automatic(unit))
        .select_related("sense", "realization", "created_by")
        .prefetch_related(Prefetch("tokens", queryset=tokens))
    )
    attestations = sorted(
        _visible_parts(user, unit, queryset),
        key=lambda item: (item.status == Attestation.Status.REJECTED, not item.is_example),
    )
    shown = attestations[:ATTESTATIONS_ON_UNIT_PAGE]
    for attestation in shown:
        attestation.quotation = quotation(list(attestation.tokens.all()))
        attestation.can_withdraw = can_withdraw_attestation(user, attestation)
    return shown, len(attestations) - len(shown)


def _relations_of(user, unit):
    outgoing = [
        (relation, relation.get_kind_display(), relation.target)
        for relation in _visible_parts(user, unit, unit.relations.active().select_related("target"))
    ]
    incoming = [
        (relation, relation.inverse_label, relation.unit)
        for relation in UnitRelation.objects.active().filter(target=unit).select_related("unit")
    ]
    return [
        {
            "relation": relation,
            "label": label,
            "unit": other,
            "outgoing": relation.unit_id == unit.pk,
        }
        for relation, label, other in outgoing + incoming
        if can_view(user, relation) and can_view(user, other)
    ]


def _frequency_rows(frequency):
    """(author, occurrences, occurrences in the core) of a computed frequency."""
    authors = Author.objects.in_bulk([row[0] for row in frequency.by_author])
    return [(authors[pk], total, core) for pk, total, core in frequency.by_author if pk in authors]


def _translations_of(user, unit):
    """Justifications of translation choices that cite the unit, as the user may see them."""
    justifications = unit.justifications.select_related(
        "translated_segment__version__project", "translated_segment__version__author"
    ).order_by("-created_at", "-pk")
    return [justification for justification in justifications if can_view(user, justification)]


def unit_detail(request, pk):
    user = request.user
    unit = _unit(user, pk)
    senses = _visible_parts(
        user,
        unit,
        unit.senses.active().prefetch_related(
            Prefetch("equivalents", queryset=Equivalent.objects.active())
        ),
    )
    for sense in senses:
        sense.visible_equivalents = _visible_parts(user, unit, sense.equivalents.all())
    frequency = UnitFrequency.objects.filter(unit=unit).first()
    reviewer = is_reviewer(user)
    missing = missing_fields(unit)
    public = not unit.is_draft and not unit.is_hidden
    attestations, attestations_more = _attestations_of(user, unit)
    edges = unit.edges
    parts, other_components = schema_parts(edges, components(user, edges))
    return render(
        request,
        "phraseology/unit_detail.html",
        {
            "unit": unit,
            "edges": edges,
            "schema_parts": parts,
            "other_components": other_components,
            "containers": containers(user, unit),
            "schema_lemmas": schema_lemmas(edges),
            "senses": senses,
            "realizations": _visible_parts(user, unit, unit.realizations.active()),
            "attestations": attestations,
            "attestations_more": attestations_more,
            "attestations_to_review": _to_review(unit).count(),
            "automatic_outside": _outside_automatic(unit)
            .filter(is_hidden=False)
            .exclude(status=Attestation.Status.REJECTED)
            .count(),
            "relations": _relations_of(user, unit),
            "translations": _translations_of(user, unit),
            "references": _visible_parts(
                user, unit, unit.references.active().select_related("work")
            ),
            "frequency": frequency,
            "frequency_rows": _frequency_rows(frequency) if frequency else [],
            "frequency_is_current": is_current(frequency, unit),
            "missing": missing,
            "can_edit": can_edit_unit(user, unit),
            "is_reviewer": reviewer,
            "can_propose": unit.is_draft and user.pk == unit.created_by_id,
            "can_validate": reviewer and unit.status == Unit.Status.PROPOSED and not missing,
            "can_contest": (
                user.is_authenticated
                and user.is_active
                and public
                and unit.status in (Unit.Status.PROPOSED, Unit.Status.VALIDATED)
            ),
            "resolve_form": (
                ResolveContestForm() if reviewer and unit.status == Unit.Status.CONTESTED else None
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def unit_edit(request, pk):
    unit = _editable_unit(request.user, pk)
    form = UnitForm(request.POST or None, instance=unit, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            revision = update_unit(form.save(commit=False), request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if revision is None:
                messages.info(request, _("Aucune modification."))
            else:
                messages.success(request, _("Les modifications sont enregistrées."))
            if unit.schema and current_frequency(unit) is None and default_layer() is not None:
                messages.info(request, FREQUENCY_LATER)
            return redirect(unit)
    return render(request, "phraseology/unit_edit.html", {"unit": unit, "form": form})


@login_required
@require_POST
def unit_frequency(request, pk):
    unit = _editable_unit(request.user, pk)
    try:
        frequency = refresh_frequency(unit, FREQUENCY_SECONDS)
    except FrequencyTooLong:
        messages.error(request, FREQUENCY_LATER)
        return redirect(f"{unit.get_absolute_url()}#frequence")
    if frequency is None:
        messages.error(
            request,
            _("La fréquence ne se calcule qu’à partir d’un schéma, sur un corpus analysé."),
        )
    else:
        messages.success(
            request,
            ngettext(
                "%(count)d occurrence repérée automatiquement.",
                "%(count)d occurrences repérées automatiquement.",
                frequency.total,
            )
            % {"count": frequency.total},
        )
    return redirect(f"{unit.get_absolute_url()}#frequence")


def _change_status(request, pk, service, success):
    unit = _unit(request.user, pk)
    try:
        revision = service(unit, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if revision is not None:
            messages.success(request, success)
    return redirect(unit)


@login_required
@require_POST
def unit_propose(request, pk):
    success = _("La fiche est proposée : elle est publique, et chacun peut la compléter.")
    return _change_status(request, pk, propose_unit, success)


@login_required
@require_POST
def unit_validate(request, pk):
    return _change_status(request, pk, validate_unit, _("La fiche est validée."))


@login_required
@require_http_methods(["GET", "POST"])
def unit_contest(request, pk):
    unit = _unit(request.user, pk)
    form = ContestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            contest_unit(unit, request.user, form.cleaned_data["argument"])
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request, _("La fiche est contestée ; votre argument ouvre la discussion.")
            )
            return redirect(f"{unit.get_absolute_url()}#discussion")
    return render(request, "phraseology/unit_contest.html", {"unit": unit, "form": form})


@login_required
@require_POST
def unit_resolve(request, pk):
    unit = _unit(request.user, pk)
    if not is_reviewer(request.user):
        raise PermissionDenied
    form = ResolveContestForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choisissez une décision et motivez-la."))
        return redirect(unit)
    data = form.cleaned_data
    try:
        resolve_contest(unit, request.user, data["status"], data["reason"])
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La contestation est levée."))
    return redirect(unit)


@login_required
@require_http_methods(["GET", "POST"])
def part_create(request, pk, kind):
    model, form_class, heading, _change_heading = _part_type(kind)
    unit = _editable_unit(request.user, pk)
    instance = model() if model is Equivalent else model(unit=unit)
    form = form_class(request.POST or None, instance=instance, unit=unit, user=request.user)
    if request.method == "POST" and form.is_valid():
        part = form.save(commit=False)
        try:
            save_part(part, request.user)
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("L’ajout est enregistré."))
            return redirect(part)
    return render(
        request, "phraseology/part_form.html", {"parent": unit, "form": form, "heading": heading}
    )


def _editable_part(user, kind, pk):
    model = _part_type(kind)[0]
    part = get_object_or_404(model.objects.active(), pk=pk)
    unit = _editable_unit(user, part.unit.pk)
    if not can_view(user, part):
        raise Http404
    return part, unit


@login_required
@require_http_methods(["GET", "POST"])
def part_edit(request, kind, pk):
    _model, form_class, _add_heading, heading = _part_type(kind)
    part, unit = _editable_part(request.user, kind, pk)
    form = form_class(request.POST or None, instance=part, unit=unit, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            revision = save_part(form.save(commit=False), request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if revision is None:
                messages.info(request, _("Aucune modification."))
            else:
                messages.success(request, _("Les modifications sont enregistrées."))
            return redirect(part)
    return render(
        request,
        "phraseology/part_form.html",
        {"parent": unit, "form": form, "heading": heading, "part": part, "kind": kind},
    )


@login_required
@require_POST
def part_withdraw(request, kind, pk):
    part, unit = _editable_part(request.user, kind, pk)
    try:
        withdraw_part(part, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("Le retrait est enregistré ; il reste dans l’historique."))
    return redirect(unit)


def _occurrences(request, unit):
    """Occurrences of the schema of a unit, offered as attestations."""
    if not unit.schema:
        return None
    attested = unit.attestations.active().exclude(status=Attestation.Status.REJECTED)
    known = {
        frozenset(token.pk for token in attestation.tokens.all())
        for attestation in attested.prefetch_related("tokens")
    }
    return _schema_occurrences(request, unit.edges, known)


def _schema_occurrences(request, edges, known=frozenset()):
    """Occurrences of a schema found automatically in the corpus, a page at a time."""
    layer = default_layer()
    if not edges or layer is None:
        return None
    core_only = request.GET.get("occurrences") != "tout"
    matches = (
        schema_matches(edges, layer, core_only)
        .select_related("token")
        .order_by(
            "token__edition__work__author__birth_year",
            "token__edition__work__cts_urn",
            "token__position",
            "part",
        )
    )
    page = Paginator(matches, OCCURRENCES_PER_PAGE).get_page(request.GET.get("page_occurrences"))
    roots = [(match.token_id, match.part, match.token.position) for match in page.object_list]
    hits = []
    for ids in occurrence_words(roots, edges, layer):
        tokens = load_tokens(ids)
        hit = quotation(tokens)
        hit.attested = frozenset(token.pk for token in tokens) in known
        hits.append(hit)
    return {"page": page, "hits": hits, "core_only": core_only, "version": corpus_version()}


@login_required
@require_http_methods(["GET", "POST"])
def attestation_add(request, pk):
    unit = _editable_unit(request.user, pk)
    place = AttestationPlaceForm(request.POST or None, unit=unit)
    evidences, errors = _chosen_attestations(request)
    found, found_errors = _chosen_attestations(request, "occurrence")
    errors += found_errors
    if request.method == "POST" and place.is_valid() and not errors:
        if evidences or found:
            created = []
            for items, origin in (
                (evidences, Attestation.Origin.MANUAL),
                (found, Attestation.Origin.QUERY),
            ):
                created += add_attestations(
                    unit,
                    items,
                    request.user,
                    sense=place.cleaned_data["sense"],
                    realization=place.cleaned_data["realization"],
                    origin=origin,
                )
            count = len(created)
            messages.success(
                request,
                ngettext(
                    "%(count)d attestation ajoutée.", "%(count)d attestations ajoutées.", count
                )
                % {"count": count},
            )
            return redirect(f"{unit.get_absolute_url()}#attestations")
        errors = [_("Cochez au moins une attestation.")]
    context = _search_page(
        request,
        evidences,
        terms=marked_search(request.user, unit.marked_form, unit.schema),
        constructions_from_form=True,
        unit=unit,
        place=place,
        errors=errors,
        keep={},
        occurrences=_occurrences(request, unit),
    )
    return render(request, "phraseology/attestation_form.html", context)


def _visible_attestation(user, pk):
    attestation = get_object_or_404(Attestation.objects.active(), pk=pk)
    attestation.unit = _unit(user, attestation.unit_id)
    if not can_view(user, attestation):
        raise Http404
    return attestation


@login_required
@require_POST
def attestation_withdraw(request, pk):
    attestation = _visible_attestation(request.user, pk)
    try:
        withdraw_attestation(attestation, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("L’attestation est retirée ; elle reste dans l’historique."))
    return redirect(f"{attestation.unit.get_absolute_url()}#attestations")


def _return_url(request, name, default):
    """Where to go back after a form: the address sent, if it belongs to the site."""
    url = request.POST.get(name) or request.GET.get(name) or ""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return default


@login_required
@require_POST
def attestation_review(request, pk):
    attestation = _visible_attestation(request.user, pk)
    status = DECISIONS.get(request.POST.get("decision", ""))
    if status is None:
        return HttpResponseBadRequest()
    try:
        review_attestation(attestation, request.user, status)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if status == Attestation.Status.VALIDATED:
            messages.success(request, _("L’attestation est validée."))
        else:
            messages.success(request, _("L’attestation est rejetée."))
    return redirect(_return_url(request, "next", attestation.get_absolute_url()))


@login_required
@require_POST
def attestation_example(request, pk):
    attestation = _visible_attestation(request.user, pk)
    try:
        set_example(attestation, request.user, request.POST.get("exemple") == "1")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect(_return_url(request, "next", attestation.get_absolute_url()))


def attestation_detail(request, pk):
    """An attestation: its words, who added and reviewed it, the doubts and the contest about it."""
    user = request.user
    attestation = get_object_or_404(
        Attestation.objects.active().select_related(
            "created_by", "reviewed_by", "sense", "realization", "passage__edition__work"
        ),
        pk=pk,
    )
    attestation.unit = _unit(user, attestation.unit_id)
    if not can_view(user, attestation):
        raise Http404
    tokens = attestation.tokens.select_related("passage__edition__work__author")
    doubts = list(
        attestation.doubts.filter(is_hidden=False).select_related("created_by", "decided_by")
    )
    reviewer = is_reviewer(user)
    active = user.is_authenticated and user.is_active
    open_to_debate = attestation.status != Attestation.Status.REJECTED and not attestation.is_hidden
    work = attestation.passage.edition.work
    reading = reverse("corpus:reading", args=[work.cts_id])
    around = urlencode({"aller": attestation.passage.reference, "fiche": attestation.unit_id})
    return render(
        request,
        "phraseology/attestation_detail.html",
        {
            "attestation": attestation,
            "quote": quotation(list(tokens.order_by("position"))),
            "reading_url": f"{reading}?{around}",
            "doubts": doubts,
            "open_doubts": sum(
                1 for doubt in doubts if doubt.status == AttestationDoubt.Status.OPEN
            ),
            "is_reviewer": reviewer,
            # Outside the core, an attestation found automatically is never validated (T2).
            "can_validate": attestation.status != Attestation.Status.VALIDATED
            and (attestation.level != Attestation.Level.AUTOMATIC or work.is_core),
            "doubt_form": DoubtForm() if active and open_to_debate else None,
            "contest_form": (
                ContestForm()
                if active and open_to_debate and not attestation.is_contested
                else None
            ),
            "resolve_form": AttestationResolveForm()
            if reviewer and attestation.is_contested
            else None,
        },
    )


@login_required
@require_POST
def attestation_doubt(request, pk):
    attestation = _visible_attestation(request.user, pk)
    form = DoubtForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Indiquez le motif du doute."))
    else:
        try:
            doubt_attestation(attestation, request.user, form.cleaned_data["reason"])
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("Le doute est enregistré ; un relecteur tranchera."))
    return redirect(f"{attestation.get_absolute_url()}#doutes")


@login_required
@require_POST
def attestation_doubts_decide(request, pk):
    attestation = _visible_attestation(request.user, pk)
    decision = request.POST.get("decision", "")
    if decision not in ("maintenir", "rejeter"):
        return HttpResponseBadRequest()
    try:
        decide_doubts(attestation, request.user, reject=decision == "rejeter")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("Les doutes sont tranchés."))
    return redirect(f"{attestation.get_absolute_url()}#doutes")


@login_required
@require_POST
def attestation_contest(request, pk):
    attestation = _visible_attestation(request.user, pk)
    form = ContestForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Indiquez votre argument."))
    else:
        try:
            contest_attestation(attestation, request.user, form.cleaned_data["argument"])
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request, _("L’attestation est contestée ; votre argument ouvre la discussion.")
            )
    return redirect(f"{attestation.get_absolute_url()}#contestation")


@login_required
@require_POST
def attestation_contest_resolve(request, pk):
    attestation = _visible_attestation(request.user, pk)
    if not is_reviewer(request.user):
        raise PermissionDenied
    form = AttestationResolveForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choisissez une décision et motivez-la."))
    else:
        data = form.cleaned_data
        try:
            resolve_attestation_contest(attestation, request.user, data["decision"], data["reason"])
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("La contestation est levée."))
    return redirect(f"{attestation.get_absolute_url()}#contestation")


def reading_word(request, pk):
    """A word of the corpus: the units it belongs to and its analysis, for the reading panel.

    The panel asks for the fragment; without script, the same content is a page of its own.
    """
    token = get_object_or_404(Token.objects.select_related("passage__edition__work__author"), pk=pk)
    user = request.user
    work = token.passage.edition.work
    reading = reverse("corpus:reading", args=[work.cts_id])
    back = _return_url(
        request, "retour", f"{reading}?{urlencode({'aller': token.passage.reference})}"
    )
    context = {
        "token": token,
        "cards": [
            unit_card(user, attestation, token) for attestation in word_attestations(user, token)
        ],
        "analysis": word_analysis(token),
        "reading_notes": word_reading_notes(token),
        "back": back,
    }
    fragment = request.GET.get("fragment") == "1"
    template = "phraseology/word_panel.html" if fragment else "phraseology/word_page.html"
    return render(request, template, context)


# Annotation of the text being read


def _annotation_forms(user, units, words):
    """A form attaching the chosen words to each of the units the user may complete."""
    return [
        (
            unit,
            AnnotationForm(
                unit=unit,
                user=user,
                auto_id=f"annotation-{unit.pk}-%s",
                initial={"unit": unit.pk, "words": words},
            ),
        )
        for unit in units
        if can_edit_unit(user, unit)
    ]


@login_required
def annotate_selection(request):
    """The entries that words chosen in the text may attest: suggested, searched, or new.

    The reading panel asks for the fragment; without script, it is a page of its own.
    """
    user = request.user
    fragment = request.GET.get("fragment") == "1"
    template = "phraseology/annotate_panel.html" if fragment else "phraseology/annotate_page.html"
    try:
        evidence = corpus_evidence(request.GET.get("mots", ""))
    except ValidationError as error:
        back = _return_url(request, "retour", reverse("corpus:index"))
        context = {"errors": error.messages, "back": back, "fragment": fragment}
        return render(request, template, context)
    tokens = evidence.tokens
    first = tokens[0]
    reading = reverse("corpus:reading", args=[first.passage.edition.work.cts_id])
    back = _return_url(
        request, "retour", f"{reading}?{urlencode({'aller': first.passage.reference})}"
    )
    words = ",".join(str(token.pk) for token in tokens)
    query = request.GET.get("q", "")
    suggested = suggested_units(user, tokens)
    found = [unit for unit in search_units(user, query) if unit not in suggested]
    # Words sighted by a reader, to attach to an entry.
    sighting = open_sighting(request.GET.get("reperage"))
    if sighting is not None and sighting_words(sighting) != words:
        sighting = None
    prefilled = {
        "forme": " ".join(token.form for token in tokens),
        "mots": words,
        "schema": guess_schema(tokens),
        "reperage": sighting.pk if sighting else "",
    }
    create_query = urlencode({name: value for name, value in prefilled.items() if value})
    return render(
        request,
        template,
        {
            "quote": quotation(tokens),
            "words": words,
            "back": back,
            "query": query,
            "fragment": fragment,
            "sighting": sighting,
            "suggested": _annotation_forms(user, suggested, words),
            "found": _annotation_forms(user, found, words),
            "create_url": f"{reverse('phraseology:unit_create')}?{create_query}",
        },
    )


@login_required
@require_POST
def annotate_attach(request):
    """Attach words chosen in the text to a unit: the attestation is proposed.

    Words of a sighting close the sighting, even when they already attested the unit.
    """
    value = request.POST.get("unit", "")
    unit = _editable_unit(request.user, int(value) if value.isdigit() else 0)
    back = _return_url(request, "next", unit.get_absolute_url())
    form = AnnotationForm(request.POST, unit=unit, user=request.user)
    if not form.is_valid():
        messages.error(
            request, " ".join(error for errors in form.errors.values() for error in errors)
        )
        return redirect(back)
    data = form.cleaned_data
    try:
        created = add_attestations(
            unit,
            [corpus_evidence(data["words"])],
            request.user,
            sense=data["sense"],
            realization=data["realization"],
            note=data["note"],
            example_proposed=data["example_proposed"],
        )
    except ContributionLimitReached as error:
        messages.error(request, str(error))
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if created:
            messages.success(
                request,
                _("L’attestation est ajoutée à la fiche « %(unit)s » ; un relecteur l’examinera.")
                % {"unit": unit.reference_form},
            )
        else:
            messages.info(request, _("Ces mots attestent déjà cette fiche."))
        sighting = open_sighting(request.POST.get("sighting"))
        if sighting is not None and sighting_words(sighting) == data["words"]:
            close_sighting(sighting, attestation_for(unit, data["words"]), request.user)
    return redirect(back)


@login_required
@require_http_methods(["GET", "POST"])
def sighting_create(request):
    """Words where a reader sees phraseology, recorded without choosing an entry."""
    fragment = request.GET.get("fragment") == "1"
    template = "phraseology/sighting_panel.html" if fragment else "phraseology/sighting_page.html"
    words = request.POST.get("words") or request.GET.get("mots", "")
    try:
        evidence = corpus_evidence(words)
    except ValidationError as error:
        back = _return_url(request, "retour", reverse("phraseology:sightings"))
        return render(request, template, {"errors": error.messages, "back": back})
    first = evidence.tokens[0]
    reading = reverse("corpus:reading", args=[first.passage.edition.work.cts_id])
    default = f"{reading}?{urlencode({'aller': first.passage.reference})}"
    back = _return_url(request, "next", _return_url(request, "retour", default))
    form = SightingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_sighting(words, request.user, form.cleaned_data["note"])
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request, _("Le repérage est enregistré ; chacun peut le rattacher à une fiche.")
            )
        return redirect(back)
    return render(
        request,
        template,
        {
            "quote": quotation(evidence.tokens),
            "words": ",".join(str(token.pk) for token in evidence.tokens),
            "back": back,
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def reading_note_create(request):
    """A public reading note about the words chosen in the reading."""
    fragment = request.GET.get("fragment") == "1"
    template = (
        "phraseology/reading_note_panel.html" if fragment else "phraseology/reading_note_page.html"
    )
    words = request.POST.get("words") or request.GET.get("mots", "")
    try:
        evidence = corpus_evidence(words)
    except ValidationError as error:
        back = _return_url(request, "retour", reverse("phraseology:annotator"))
        return render(request, template, {"errors": error.messages, "back": back})
    first = evidence.tokens[0]
    reading = reverse("corpus:reading", args=[first.passage.edition.work.cts_id])
    default = f"{reading}?{urlencode({'aller': first.passage.reference})}"
    back = _return_url(request, "next", _return_url(request, "retour", default))
    form = ReadingNoteForm(request.POST or None)
    if request.method == "POST":
        if not form.is_valid():
            messages.error(request, _("Écrivez la note."))
        else:
            try:
                create_reading_note(words, request.user, form.cleaned_data["text"])
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, _("La note de lecture est publiée."))
        return redirect(back)
    return render(
        request,
        template,
        {
            "quote": quotation(evidence.tokens),
            "words": ",".join(str(token.pk) for token in evidence.tokens),
            "back": back,
            "form": form,
        },
    )


SIGHTINGS_PER_PAGE = 50


def sighting_list(request):
    """The sightings to attach to an entry, and those already attached or dismissed."""
    status = request.GET.get("statut", "")
    if status not in Sighting.Status.values:
        status = Sighting.Status.OPEN
    sightings = Sighting.objects.filter(status=status, is_hidden=False).select_related(
        "passage__edition__work", "created_by", "decided_by", "attestation"
    )
    page = Paginator(sightings, SIGHTINGS_PER_PAGE).get_page(request.GET.get("page"))
    tokens = Token.objects.select_related("passage__edition__work__author")
    items = []
    for sighting in page.object_list:
        words = list(tokens.filter(pk__in=sighting.tokens.values("pk")).order_by("position"))
        ids = ",".join(str(word.pk) for word in words)
        work = sighting.passage.edition.work
        reading = reverse("corpus:reading", args=[work.cts_id])
        around = urlencode({"aller": sighting.passage.reference, "annoter": "1"})
        attach = urlencode(
            {"mots": ids, "reperage": sighting.pk, "retour": request.get_full_path()}
        )
        items.append(
            {
                "sighting": sighting,
                "quote": quotation(words),
                "reading_url": f"{reading}?{around}",
                "attach_url": f"{reverse('phraseology:annotate_selection')}?{attach}",
            }
        )
    counts = dict(
        Sighting.objects.filter(is_hidden=False)
        .order_by()
        .values_list("status")
        .annotate(count=Count("pk"))
    )
    return render(
        request,
        "phraseology/sighting_list.html",
        {
            "page": page,
            "sightings": items,
            "status": status,
            "tabs": [
                (value, label, counts.get(value, 0)) for value, label in Sighting.Status.choices
            ],
            "is_reviewer": is_reviewer(request.user),
        },
    )


@login_required
@require_POST
def sighting_dismiss(request, pk):
    sighting = get_object_or_404(Sighting, pk=pk, is_hidden=False)
    try:
        dismiss_sighting(sighting, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("Le repérage est classé sans suite."))
    return redirect(f"{reverse('phraseology:sightings')}#reperage-{sighting.pk}")


@login_required
def suggestion_panel(request):
    """An occurrence of the schema of a unit, found in the text, to confirm as an attestation."""
    fragment = request.GET.get("fragment") == "1"
    template = (
        "phraseology/suggestion_panel.html" if fragment else "phraseology/suggestion_page.html"
    )
    value = request.GET.get("fiche", "")
    unit = _editable_unit(request.user, int(value) if value.isdigit() else 0)
    try:
        evidence = corpus_evidence(request.GET.get("mots", ""))
    except ValidationError as error:
        back = _return_url(request, "retour", unit.get_absolute_url())
        context = {"errors": error.messages, "back": back, "fragment": fragment}
        return render(request, template, context)
    tokens = evidence.tokens
    first = tokens[0]
    reading = reverse("corpus:reading", args=[first.passage.edition.work.cts_id])
    back = _return_url(
        request, "retour", f"{reading}?{urlencode({'aller': first.passage.reference})}"
    )
    return render(
        request,
        template,
        {
            "unit": unit,
            "quote": quotation(tokens),
            "words": ",".join(str(token.pk) for token in tokens),
            "core": first.passage.edition.work.is_core,
            "back": back,
            "fragment": fragment,
        },
    )


@login_required
@require_POST
def suggestion_confirm(request):
    """Confirm a suggested occurrence: proposed in the core, found automatically outside it."""
    value = request.POST.get("unit", "")
    unit = _editable_unit(request.user, int(value) if value.isdigit() else 0)
    back = _return_url(request, "next", unit.get_absolute_url())
    try:
        created = confirm_suggestion(unit, request.POST.get("words", ""), request.user)
    except ContributionLimitReached as error:
        messages.error(request, str(error))
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if created:
            messages.success(
                request,
                _("L’occurrence est enregistrée comme attestation de la fiche « %(unit)s ».")
                % {"unit": unit.reference_form},
            )
        else:
            messages.info(request, _("Ces mots attestent déjà cette fiche."))
    return redirect(back)


# Completeness and following of the annotation

REVIEW_PASSAGES_PER_PAGE = 50


def _annotating_url(passage):
    reading = reverse("corpus:reading", args=[passage.edition.work.cts_id])
    return f"{reading}?{urlencode({'aller': passage.reference, 'annoter': '1'})}"


def review_queue(request):
    """The progress of the works of the core, and the passages of one not yet entirely reviewed."""
    works = (
        Work.objects.filter(is_core=True, editions__is_current=True)
        .select_related("author")
        .distinct()
        .order_by("author__birth_year", "cts_urn")
    )
    progress = work_progress(works)
    chosen = request.GET.get("oeuvre", "")
    selected = next((row for row in progress if row["work"].cts_id == chosen), None)
    page, items = None, []
    if selected is not None:
        passages = passages_to_review(selected["work"]).select_related("edition__work")
        page = Paginator(passages, REVIEW_PASSAGES_PER_PAGE).get_page(request.GET.get("page"))
        shown = list(page.object_list)
        counts, validated = attestation_counts(shown)
        items = [
            {
                "passage": passage,
                "attestations": counts.get(passage.pk, 0),
                "validated": validated.get(passage.pk, 0),
                "reading_url": _annotating_url(passage),
            }
            for passage in shown
        ]
    return render(
        request,
        "phraseology/review_queue.html",
        {
            "progress": progress,
            "selected": selected,
            "page": page,
            "passages": items,
            "is_reviewer": is_reviewer(request.user),
        },
    )


@login_required
@require_POST
def passage_review(request, pk):
    """A reviewer declares a passage entirely reviewed, or withdraws the declaration."""
    passage = get_object_or_404(Passage.objects.select_related("edition__work__author"), pk=pk)
    action = request.POST.get("action", "")
    if action not in ("relu", "retirer"):
        return HttpResponseBadRequest()
    try:
        if action == "relu":
            mark_reviewed(passage, request.user)
        else:
            withdraw_review(passage, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if action == "relu":
            message = _("Le passage %(citation)s est déclaré entièrement relu.")
        else:
            message = _("Le passage %(citation)s n’est plus déclaré entièrement relu.")
        messages.success(request, message % {"citation": passage.citation})
    return redirect(_return_url(request, "next", _annotating_url(passage)))


@login_required
def annotator_page(request):
    """What the user added in the texts, with the status of each addition."""
    return render(request, "phraseology/annotator.html", annotator_summary(request.user))


@login_required
def reviewer_page(request):
    """What waits for reviewers: proposed attestations by passage, doubts, contests, queues."""
    if not is_reviewer(request.user):
        raise PermissionDenied
    queue = reviewer_queue()
    for group in queue["groups"]:
        group["reading_url"] = _annotating_url(group["passage"])
    return render(request, "phraseology/reviewer.html", queue)


def figures_page(request):
    """The public figures of the annotation."""
    return render(request, "phraseology/figures.html", public_figures())


# Survey of the occurrences: those of the core reviewed in batches, the others shown as found
# automatically

SURVEY_PER_PAGE = 50
SURVEY_TABS = (
    ("a-examiner", Attestation.Status.PROPOSED, gettext_lazy("à examiner")),
    ("validees", Attestation.Status.VALIDATED, gettext_lazy("validées")),
    ("rejetees", Attestation.Status.REJECTED, gettext_lazy("rejetées")),
    ("toutes", None, gettext_lazy("toutes")),
)
SURVEY_SCOPES = (
    ("noyau", True, gettext_lazy("noyau")),
    ("hors-noyau", False, gettext_lazy("hors du noyau")),
)


def _scope_attestations(unit, core):
    return (
        unit.attestations.active()
        .filter(is_hidden=False, passage__edition__work__is_core=core)
        .order_by(
            "passage__edition__work__author__birth_year",
            "passage__edition__work__cts_urn",
            "passage__order",
            "pk",
        )
    )


def _survey_summary(rows, shapes):
    """For each shape, how many attestations realize it, by status."""
    summary = {}
    for attestation_id, status in rows:
        shape = shapes.get(attestation_id, "")
        row = summary.setdefault(
            shape, {"shape": shape, "total": 0, "proposed": 0, "validated": 0, "rejected": 0}
        )
        row["total"] += 1
        row[status] += 1
    return sorted(summary.values(), key=lambda row: (-row["total"], row["shape"]))


def unit_survey(request, pk):
    user = request.user
    unit = _unit(user, pk)
    scopes = {value: core for value, core, _label in SURVEY_SCOPES}
    scope = request.GET.get("portee", "")
    if scope not in scopes:
        scope = SURVEY_SCOPES[0][0]
    core = scopes[scope]
    rows = list(_scope_attestations(unit, core).values_list("pk", "status"))
    shapes = attestation_shapes([row[0] for row in rows], default_layer(), unit.edges)
    wanted = {value: status for value, status, _label in SURVEY_TABS}
    status = request.GET.get("statut", "")
    if status not in wanted:
        # Outside the core, nothing waits for a review.
        status = "a-examiner" if core else "toutes"
    shape = request.GET.get("forme", "")[:300]
    selected = [
        attestation_id
        for attestation_id, attestation_status in rows
        if wanted[status] in (None, attestation_status)
        and (not shape or shapes.get(attestation_id) == shape)
    ]
    page = Paginator(selected, SURVEY_PER_PAGE).get_page(request.GET.get("page"))
    tokens = Token.objects.select_related("passage__edition__work__author")
    loaded = (
        Attestation.objects.select_related("realization", "sense")
        .prefetch_related(Prefetch("tokens", queryset=tokens))
        .in_bulk(page.object_list)
    )
    attestations = []
    for attestation_id in page.object_list:
        attestation = loaded[attestation_id]
        attestation.quotation = quotation(list(attestation.tokens.all()))
        attestation.shape = shapes.get(attestation_id, "")
        attestations.append(attestation)
    survey = UnitSurvey.objects.select_related("surveyed_by").filter(unit=unit).first()
    tabs = [
        (
            value,
            label if core or value != "a-examiner" else gettext_lazy("repérées automatiquement"),
            sum(1 for _pk, row_status in rows if tab_status in (None, row_status)),
        )
        for value, tab_status, label in SURVEY_TABS
    ]
    scope_tabs = [
        (value, label, _scope_attestations(unit, tab_core).count())
        for value, tab_core, label in SURVEY_SCOPES
    ]
    return render(
        request,
        "phraseology/unit_survey.html",
        {
            "unit": unit,
            "edges": unit.edges,
            "survey": survey,
            "survey_is_current": is_current(survey, unit),
            "version": corpus_version(),
            "scope": scope,
            "core": core,
            "scope_tabs": scope_tabs,
            "shapes": _survey_summary(rows, shapes),
            "tabs": tabs,
            "status": status,
            "shape": shape,
            "page": page,
            "attestations": attestations,
            "can_run": bool(unit.schema) and can_edit_unit(user, unit),
            "is_reviewer": is_reviewer(user),
            "can_validate": core and is_reviewer(user),
            "realizations": _visible_parts(user, unit, unit.realizations.active()),
            "senses": _visible_parts(user, unit, unit.senses.active()),
        },
    )


@login_required
@require_POST
def unit_survey_run(request, pk):
    unit = _editable_unit(request.user, pk)
    try:
        survey = survey_unit(unit, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(
            request,
            ngettext(
                "%(count)d attestation ajoutée au relevé.",
                "%(count)d attestations ajoutées au relevé.",
                survey.added,
            )
            % {"count": survey.added},
        )
        if survey.remaining:
            messages.info(
                request,
                ngettext(
                    "%(count)d occurrence reste à relever : relancez le relevé.",
                    "%(count)d occurrences restent à relever : relancez le relevé.",
                    survey.remaining,
                )
                % {"count": survey.remaining},
            )
    return redirect("phraseology:unit_survey", pk=unit.pk)


def _chosen_part(queryset, value):
    value = value or ""
    return queryset.active().filter(pk=int(value)).first() if value.isdigit() else None


@login_required
@require_POST
def unit_survey_review(request, pk):
    unit = _unit(request.user, pk)
    if not is_reviewer(request.user):
        raise PermissionDenied
    status = DECISIONS.get(request.POST.get("decision", ""))
    if status is None:
        return HttpResponseBadRequest()
    ids = [int(value) for value in request.POST.getlist("attestation") if value.isdigit()]
    if not ids:
        messages.error(request, _("Cochez au moins une attestation."))
    else:
        try:
            revisions = review_attestations(
                unit,
                ids,
                request.user,
                status,
                sense=_chosen_part(unit.senses, request.POST.get("sens")),
                realization=_chosen_part(unit.realizations, request.POST.get("realisation")),
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            count = len(revisions)
            if status == Attestation.Status.VALIDATED:
                message = ngettext(
                    "%(count)d attestation validée.", "%(count)d attestations validées.", count
                )
            else:
                message = ngettext(
                    "%(count)d attestation rejetée.", "%(count)d attestations rejetées.", count
                )
            messages.success(request, message % {"count": count})
    kept = {
        name: request.POST[name]
        for name in ("portee", "statut", "forme", "page")
        if request.POST.get(name)
    }
    query = f"?{urlencode(kept)}" if kept else ""
    return redirect(f"{reverse('phraseology:unit_survey', args=[unit.pk])}{query}#examen")


# Neologisms

NEOLOGISMS_PER_PAGE = 50


def _neologism(user, pk):
    neologism = get_object_or_404(
        Neologism.objects.select_related("created_by", "validated_by"), pk=pk
    )
    if not can_view(user, neologism):
        raise Http404
    return neologism


def _editable_neologism(user, pk):
    neologism = _neologism(user, pk)
    if not can_edit_neologism(user, neologism):
        raise PermissionDenied
    return neologism


def _references(request):
    data = request.POST if request.method == "POST" else None
    return ReferenceFormSet(data, prefix="references", form_kwargs={"user": request.user})


def _reference_evidences(references):
    return [evidence for evidence in (form.evidence() for form in references) if evidence]


def neologism_list(request):
    active = NeologismEquivalent.objects.active().filter(is_hidden=False)
    neologisms = Neologism.objects.filter(is_hidden=False).prefetch_related(
        Prefetch("equivalents", queryset=active, to_attr="shown_equivalents")
    )
    query = " ".join(request.GET.get("q", "").split())[:100]
    if query:
        matching = active.filter(expression__icontains=query).values("neologism")
        neologisms = neologisms.filter(Q(form__icontains=query) | Q(pk__in=matching))
    formation = request.GET.get("formation", "")
    if formation in Neologism.Formation.values:
        neologisms = neologisms.filter(formation=formation)
    page = Paginator(neologisms, NEOLOGISMS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "phraseology/neologism_list.html",
        {
            "page": page,
            "query": query,
            "formation": formation,
            "formations": Neologism.Formation.choices,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def neologism_create(request):
    form = NeologismCreateForm(request.POST or None, user=request.user)
    references = _references(request)
    evidences, errors = _chosen_attestations(request)
    if request.method == "POST":
        valid = form.is_valid() & references.is_valid()
        for message in errors:
            form.add_error(None, message)
        if valid and not errors:
            data = form.cleaned_data
            equivalent = NeologismEquivalent(
                language=data["language"], expression=data["expression"]
            )
            all_evidences = evidences + _reference_evidences(references)
            neologism = form.save(commit=False)
            try:
                create_neologism(neologism, request.user, equivalent, all_evidences)
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("Le néologisme est ajouté au lexique."))
                return redirect(neologism)
    context = _search_page(
        request, evidences, form=form, references=references, keep={}, attesting=False
    )
    return render(request, "phraseology/neologism_create.html", context)


def neologism_detail(request, pk):
    user = request.user
    neologism = _neologism(user, pk)
    equivalents = []
    for equivalent in neologism.equivalents.active():
        equivalent.neologism = neologism
        if can_view(user, equivalent):
            equivalents.append(equivalent)
    can_edit = can_edit_neologism(user, neologism)
    return render(
        request,
        "phraseology/neologism_detail.html",
        {
            "neologism": neologism,
            "equivalents": equivalents,
            "evidences": visible_evidences(user, neologism.evidences.all(), neologism=neologism),
            "can_edit": can_edit,
            "withdraw_url": "phraseology:neologism_evidence_withdraw",
            "can_validate": (is_reviewer(user) and neologism.status == Neologism.Status.PROPOSED),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def neologism_edit(request, pk):
    neologism = _editable_neologism(request.user, pk)
    form = NeologismForm(request.POST or None, instance=neologism, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision = update_neologism(form.save(commit=False), request.user)
        if revision is None:
            messages.info(request, _("Aucune modification."))
        else:
            messages.success(request, _("Les modifications sont enregistrées."))
        return redirect(neologism)
    context = {"form": form, "parent": neologism, "heading": _("Modifier le néologisme")}
    return render(request, "phraseology/part_form.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def neologism_equivalent_add(request, pk):
    neologism = _editable_neologism(request.user, pk)
    form = NeologismEquivalentForm(
        request.POST or None, instance=NeologismEquivalent(neologism=neologism), user=request.user
    )
    if request.method == "POST" and form.is_valid():
        equivalent = form.save(commit=False)
        save_neologism_equivalent(equivalent, request.user)
        messages.success(request, _("L’ajout est enregistré."))
        return redirect(equivalent)
    context = {"form": form, "parent": neologism, "heading": _("Ajouter un équivalent")}
    return render(request, "phraseology/part_form.html", context)


@login_required
@require_POST
def neologism_equivalent_withdraw(request, pk):
    equivalent = get_object_or_404(NeologismEquivalent.objects.active(), pk=pk)
    equivalent.neologism = _neologism(request.user, equivalent.neologism_id)
    if not can_view(request.user, equivalent):
        raise Http404
    try:
        withdraw_neologism_equivalent(equivalent, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("Le retrait est enregistré ; il reste dans l’historique."))
    return redirect(equivalent.neologism)


@login_required
@require_http_methods(["GET", "POST"])
def neologism_evidence_add(request, pk):
    neologism = _editable_neologism(request.user, pk)
    references = _references(request)
    evidences, errors = _chosen_attestations(request)
    if request.method == "POST" and references.is_valid() and not errors:
        new_evidences = evidences + _reference_evidences(references)
        if new_evidences:
            add_neologism_evidences(neologism, new_evidences, request.user)
            count = len(new_evidences)
            messages.success(
                request,
                ngettext("%(count)d preuve ajoutée.", "%(count)d preuves ajoutées.", count)
                % {"count": count},
            )
            return redirect(f"{neologism.get_absolute_url()}#preuves")
        errors = [_("Cochez une attestation ou citez un ouvrage.")]
    context = _search_page(
        request,
        evidences,
        neologism=neologism,
        references=references,
        errors=errors,
        keep={},
        attesting=False,
    )
    return render(request, "phraseology/neologism_evidence_form.html", context)


@login_required
@require_POST
def neologism_evidence_withdraw(request, pk):
    evidence = get_object_or_404(Evidence, pk=pk, neologism__isnull=False)
    evidence.neologism = _neologism(request.user, evidence.neologism_id)
    try:
        withdraw_neologism_evidence(evidence, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La preuve est retirée."))
    return redirect(f"{evidence.neologism.get_absolute_url()}#preuves")


@login_required
@require_POST
def neologism_validate(request, pk):
    neologism = _neologism(request.user, pk)
    if validate_neologism(neologism, request.user) is not None:
        messages.success(request, _("Le néologisme est validé."))
    return redirect(neologism)


# Abstract words

ABSTRACT_WORDS_PER_PAGE = 50
# The time given to count the words of the core that meet each rule of an abstract word.
RULE_COUNT_SECONDS = 3
# Units shown on the page of an abstract word.
ABSTRACT_WORD_UNITS = 50


def _abstract_word(user, pk):
    word = get_object_or_404(
        AbstractWord.objects.select_related("created_by", "validated_by"), pk=pk
    )
    if not can_view(user, word):
        raise Http404
    return word


def _rule_count(rule, layer):
    """The words of the core that meet a rule, or None when they take too long to count."""
    with TimeLimit(RULE_COUNT_SECONDS) as limit:
        count = (
            TokenAnalysis.objects.filter(
                rule_condition(rule),
                layer=layer,
                token__edition__is_current=True,
                token__edition__work__is_core=True,
            )
            .order_by()
            .count()
        )
    return None if limit.exceeded else count


def abstract_word_list(request):
    words = AbstractWord.objects.filter(is_hidden=False)
    query = " ".join(request.GET.get("q", "").split())[:100]
    if query:
        words = words.filter(Q(name__icontains=query) | Q(label__icontains=query))
    page = Paginator(words, ABSTRACT_WORDS_PER_PAGE).get_page(request.GET.get("page"))
    for word in page:
        word.rule_labels = [rule_label(rule) for rule in word.rules]
    return render(request, "phraseology/abstract_word_list.html", {"page": page, "query": query})


@login_required
@require_http_methods(["GET", "POST"])
def abstract_word_create(request):
    form = AbstractWordForm(request.POST or None, instance=AbstractWord(), user=request.user)
    if request.method == "POST" and form.is_valid():
        word = form.save(commit=False)
        try:
            create_abstract_word(word, request.user)
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        else:
            messages.success(request, _("Le mot abstrait est proposé."))
            return redirect(word)
    return render(
        request,
        "phraseology/abstract_word_form.html",
        {"form": form, "heading": _("Proposer un mot abstrait")},
    )


def abstract_word_detail(request, pk):
    user = request.user
    word = _abstract_word(user, pk)
    layer = default_layer()
    rules = [
        {"label": rule_label(rule), "count": _rule_count(rule, layer) if layer else None}
        for rule in word.rules
    ]
    written = str(word)
    units = (
        visible_units(user)
        .filter(Q(schema__contains=written) | Q(reference_form__contains=written))
        .order_by("reference_form", "pk")
    )
    return render(
        request,
        "phraseology/abstract_word_detail.html",
        {
            "word": word,
            "rules": rules,
            "units": units[:ABSTRACT_WORD_UNITS],
            "counted": layer is not None,
            "can_edit": can_edit_abstract_word(user, word),
            "can_validate": is_reviewer(user) and word.status == AbstractWord.Status.PROPOSED,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def abstract_word_edit(request, pk):
    word = _abstract_word(request.user, pk)
    if not can_edit_abstract_word(request.user, word):
        raise PermissionDenied
    form = AbstractWordForm(request.POST or None, instance=word, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision = update_abstract_word(form.save(commit=False), request.user)
        if revision is None:
            messages.info(request, _("Aucune modification."))
        else:
            messages.success(request, _("Les modifications sont enregistrées."))
        return redirect(word)
    return render(
        request,
        "phraseology/abstract_word_form.html",
        {"form": form, "word": word, "heading": _("Modifier le mot abstrait")},
    )


@login_required
@require_POST
def abstract_word_validate(request, pk):
    word = _abstract_word(request.user, pk)
    if validate_abstract_word(word, request.user) is not None:
        messages.success(request, _("Le mot abstrait est validé."))
    return redirect(word)


# Candidates

CANDIDATES_PER_PAGE = 50


def _can_reject(user):
    return user.is_authenticated and user.is_active and not is_limited(user)


def candidate_list(request):
    status = request.GET.get("statut", "")
    if status not in Candidate.Status.values:
        status = Candidate.Status.PENDING
    candidates = Candidate.objects.filter(status=status).select_related("unit")
    query = normalize(" ".join(request.GET.get("q", "").split()))[:100]
    if query:
        candidates = candidates.filter(Q(head__startswith=query) | Q(dependent__startswith=query))
    relation = request.GET.get("relation", "")
    if relation in Candidate.RELATION_LABELS:
        candidates = candidates.filter(relation=relation)
    page = Paginator(candidates, CANDIDATES_PER_PAGE).get_page(request.GET.get("page"))
    shown = list(page.object_list)
    for candidate in shown:
        candidate.unit_visible = candidate.unit is not None and can_view(
            request.user, candidate.unit
        )
    counts = dict(Candidate.objects.order_by().values_list("status").annotate(count=Count("pk")))
    return render(
        request,
        "phraseology/candidate_list.html",
        {
            "page": page,
            "candidates": shown,
            "status": status,
            "query": query,
            "relation": relation,
            "relations": list(Candidate.RELATION_LABELS.items()),
            "tabs": [
                (value, label, counts.get(value, 0)) for value, label in Candidate.Status.choices
            ],
            "latest": Candidate.objects.order_by("-extracted_at").first(),
            "can_reject": _can_reject(request.user),
        },
    )


@require_http_methods(["GET", "POST"])
def candidate_detail(request, pk):
    candidate = get_object_or_404(Candidate.objects.select_related("unit", "decided_by"), pk=pk)
    user = request.user
    if request.method == "POST" and not user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    pending = candidate.status == Candidate.Status.PENDING
    form = None
    if pending and user.is_authenticated and user.is_active:
        form = CandidateUnitForm(request.POST or None, user=user)
    evidences, errors = _chosen_attestations(request)
    if request.method == "POST":
        if form is None:
            raise PermissionDenied
        valid = form.is_valid()
        for message in errors:
            form.add_error(None, message)
        if valid and not errors:
            definition = form.cleaned_data["definition"]
            try:
                unit = create_unit_from_candidate(
                    candidate, user, form.save(commit=False), definition, evidences
                )
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(
                    request,
                    _("La fiche est créée : c’est un brouillon visible de vous seul."),
                )
                return redirect(unit)
    occurrences = _schema_occurrences(request, parse_schema(candidate.schema))
    shown = {hit.word_ids for hit in occurrences["hits"]} if occurrences else set()
    chosen = [quotation(evidence.tokens) for evidence in evidences]
    existing = [
        unit
        for unit in Unit.objects.filter(schema=candidate.schema, is_hidden=False)
        if can_view(user, unit)
    ]
    return render(
        request,
        "phraseology/candidate_detail.html",
        {
            "candidate": candidate,
            "unit_visible": candidate.unit is not None and can_view(user, candidate.unit),
            "form": form,
            "occurrences": occurrences,
            "chosen": [quote for quote in chosen if quote.word_ids not in shown],
            "chosen_ids": {quote.word_ids for quote in chosen},
            "existing": existing,
            "can_reject": pending and _can_reject(user),
            "can_reopen": not pending and is_reviewer(user),
        },
    )


@login_required
@require_POST
def candidate_reject(request, pk):
    candidate = get_object_or_404(Candidate, pk=pk)
    try:
        reject_candidate(candidate, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("Le candidat est rejeté."))
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse("phraseology:candidate_list")
    return redirect(next_url)


@login_required
@require_POST
def candidate_reopen(request, pk):
    candidate = get_object_or_404(Candidate, pk=pk)
    reopen_candidate(candidate, request.user)
    messages.success(request, _("Le candidat est remis à examiner."))
    return redirect(candidate)


@login_required
@require_POST
def candidate_attach(request, pk):
    candidate = get_object_or_404(Candidate, pk=pk)
    unit_pk = request.POST.get("unit", "")
    unit = get_object_or_404(
        Unit, pk=int(unit_pk) if unit_pk.isdigit() else 0, schema=candidate.schema
    )
    if not can_view(request.user, unit):
        raise Http404
    try:
        retain_candidate(candidate, request.user, unit)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect(candidate)
    messages.success(request, _("Le candidat est retenu pour cette fiche."))
    return redirect(unit)


# Known units in a translated sentence


def units_in_sentence(request, version_pk, segment_pk):
    """Known units of a translated sentence: the editor panel, or a page without script."""
    version = get_object_or_404(
        TranslationVersion.objects.select_related("project__source_text", "author"),
        pk=version_pk,
    )
    if not can_view(request.user, version):
        raise Http404
    source = version.project.source_text
    segment = get_object_or_404(source.segments, pk=segment_pk)
    text = ""
    translated = TranslatedSegment.objects.filter(version=version, segment=segment).first()
    if translated is not None:
        translated.version = version
        # The author's working text, or the latest public step for others.
        text = shown_text(request.user, translated)
    tokens, spots = spot_units(text, request.user)
    fragment = bool(request.GET.get("fragment"))
    context = {
        "version": version,
        "segment": segment,
        "source_language": source.language,
        "text": text,
        "tokens": tokens,
        "spots": spots,
        "marked": {index for spot in spots for index in spot.positions},
        "fragment": fragment,
        "can_translate": can_translate(request.user, version),
    }
    template = "phraseology/spotted_units.html" if fragment else "phraseology/spotted_page.html"
    return render(request, template, context)


# Searches that find nothing

NEGATIVE_SEARCHES_PER_PAGE = 50


def negative_search_list(request):
    searches = NegativeSearch.objects.filter(is_hidden=False).select_related("created_by")
    page = Paginator(searches, NEGATIVE_SEARCHES_PER_PAGE).get_page(request.GET.get("page"))
    page.object_list = list(page.object_list)
    for search in page.object_list:
        form = recorded_search_form(search)
        search.description = form.description if form is not None else ""
    return render(
        request,
        "phraseology/negative_search_list.html",
        {"page": page, "version": corpus_version()},
    )


def negative_search_detail(request, pk):
    search = get_object_or_404(NegativeSearch.objects.select_related("created_by"), pk=pk)
    if not can_view(request.user, search):
        raise Http404
    form = recorded_search_form(search)
    version = corpus_version()
    unchanged = search.corpus_version == version.label
    hits = None
    # The search is run again only on a corpus that changed since it was recorded.
    with TimeLimit() as limit:
        if form is not None and not unchanged:
            hits = form.hits().count()
    return render(
        request,
        "phraseology/negative_search_detail.html",
        {
            "search": search,
            "valid": form is not None,
            "description": form.description if form is not None else "",
            "version": version,
            "unchanged": unchanged,
            "hits": hits,
            "too_broad": limit.exceeded,
        },
    )


@login_required
@require_POST
def negative_search_create(request):
    form = NegativeSearchForm(request.POST)
    query = search_query(QueryDict(request.POST.get("query", "")))
    if form.is_valid():
        search = form.save(commit=False)
        search.query = query
        try:
            record_negative_search(search, request.user)
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request, _("La recherche infructueuse est enregistrée, avec la version du corpus.")
            )
            return redirect(search)
    else:
        messages.error(request, _("Indiquez l’expression cherchée."))
    url = reverse("corpus:search")
    return redirect(f"{url}?{query}" if query else url)


# Queries by schema

SCHEMA_RESULTS_PER_PAGE = 50
SLOT_ROWS = 100


def _filler_rows(matches, edges, layer):
    """The most frequent lemmas of the open slot, each with the schema that names it."""
    written = format_schema(edges)
    rows = slot_fillers(matches, edges, layer)
    return [(lemma, count, written.replace(SLOT, lemma)) for lemma, count in rows[:SLOT_ROWS]], len(
        rows
    )


def schema_search(request):
    form = SchemaSearchForm(request.GET if "schema" in request.GET else None)
    layer = default_layer()
    context = {"form": form, "version": corpus_version(), "searched": False, "layer": layer}
    if form.is_bound and form.is_valid() and layer is not None:
        edges = form.cleaned_data["schema"]
        matches = schema_matches(edges, layer, form.core_only)
        if form.cleaned_data["text_forms"]:
            matches = matches.filter(token__edition__work__form__in=form.cleaned_data["text_forms"])
        ordered = matches.select_related("token").order_by(
            "token__edition__work__author__birth_year",
            "token__edition__work__cts_urn",
            "token__position",
            "part",
        )
        has_slot = any(edge.dependent == SLOT for edge in edges)
        context["schema_parts"], context["other_components"] = schema_parts(
            edges, components(request.user, edges)
        )
        with TimeLimit() as limit:
            page = Paginator(ordered, SCHEMA_RESULTS_PER_PAGE).get_page(request.GET.get("page"))
            roots = [
                (match.token_id, match.part, match.token.position) for match in page.object_list
            ]
            context.update(
                searched=True,
                edges=edges,
                page=page,
                hits=[quotation(load_tokens(ids)) for ids in occurrence_words(roots, edges, layer)],
                distribution=[(author, total) for author, total, _core in count_by_author(matches)],
                core_only=form.core_only,
                has_slot=has_slot,
            )
            if has_slot:
                context["fillers"], context["filler_count"] = _filler_rows(matches, edges, layer)
        context["too_broad"] = limit.exceeded
    return render(request, "phraseology/schema_search.html", context)


@require_GET
def schema_help_lemmas(request):
    """The lemmas the words of a text may have, for the drawing of a schema."""
    words = word_choices(request.user, request.GET.get("formes", "")[:1000])
    return JsonResponse({"words": words})


@require_GET
def schema_help_abstracts(request):
    """The abstract words a drawing may use, found by their name or label."""
    return JsonResponse({"words": abstract_words(request.user, request.GET.get("q", ""))})


@require_GET
def schema_help_check(request):
    """A schema checked while it is drawn, with its occurrences in the core if asked."""
    return JsonResponse(
        check_schema(
            request.GET.get("schema", ""),
            slot=request.GET.get("case_vide") == "1",
            count=request.GET.get("compter") == "1",
            user=request.user,
        )
    )


@require_GET
def schema_help_form(request):
    """The reference form being written: the units it marks, and the known units to suggest."""
    return JsonResponse(
        form_help(request.user, request.GET.get("forme", ""), request.GET.get("schema", ""))
    )


@require_GET
def schema_help_units(request):
    """Units to insert in the drawing of a schema, found by their reference form."""
    return JsonResponse({"units": unit_schemas(request.user, request.GET.get("fiche", ""))})


# Profiles of collocations


def collocation_profile(request, lemma=""):
    scope = request.GET.get("portee", "")
    if scope not in Collocation.Scope.values:
        scope = Collocation.Scope.CORE
    asked = normalize(request.GET.get("lemme", "").strip())[:200]
    if asked and asked != lemma:
        url = reverse("phraseology:collocation_lemma", args=[asked])
        return redirect(f"{url}?{urlencode({'portee': scope})}")
    lemma = normalize(lemma)[:200]
    return render(
        request,
        "phraseology/collocation_profile.html",
        {
            "lemma": lemma,
            "scope": scope,
            "scope_label": Collocation.Scope(scope).label,
            "scopes": Collocation.Scope.choices,
            "sections": profile(lemma, scope) if lemma else [],
            "computed": profile_computed(scope),
            "schema_scope": "core" if scope == Collocation.Scope.CORE else "all",
            "prose_only": scope == Collocation.Scope.PROSE,
        },
    )
