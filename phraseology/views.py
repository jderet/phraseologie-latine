from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from corpus.models import Token
from corpus.search import quotation
from corpus.text import normalize
from corpus.views import search_context
from justifications.services import corpus_evidence
from moderation.registry import can_view

from .forms import (
    AttestationPlaceForm,
    EquivalentForm,
    RealizationForm,
    RelationForm,
    SenseForm,
    UnitCreateForm,
    UnitForm,
    UnitReferenceForm,
)
from .models import (
    Attestation,
    Equivalent,
    Kind,
    Realization,
    Sense,
    Unit,
    UnitReference,
    UnitRelation,
)
from .permissions import can_edit_unit, can_withdraw_attestation
from .services import (
    add_attestations,
    create_unit,
    save_part,
    update_unit,
    withdraw_attestation,
    withdraw_part,
)

UNITS_PER_PAGE = 50
SEARCH_RESULTS = 20
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


def _unit(user, pk):
    unit = get_object_or_404(Unit.objects.select_related("created_by"), pk=pk)
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


def _chosen_attestations(request):
    """Attestations ticked in the form, and the errors of those that are not valid."""
    evidences, errors = [], []
    if request.method != "POST":
        return evidences, errors
    for value in dict.fromkeys(request.POST.getlist("attestation")):
        try:
            evidences.append(corpus_evidence(value))
        except ValidationError as error:
            errors.extend(error.messages)
    return evidences, errors


def _search_page(request, evidences, **extra):
    """The corpus search of the page, and the attestations already ticked."""
    search = search_context(request, SEARCH_RESULTS)
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


@login_required
@require_http_methods(["GET", "POST"])
def unit_create(request):
    form = UnitCreateForm(
        request.POST or None,
        user=request.user,
        initial={"reference_form": request.GET.get("forme", "")},
    )
    evidences, errors = _chosen_attestations(request)
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
                messages.success(
                    request, _("La fiche est créée : c’est un brouillon visible de vous seul.")
                )
                return redirect(unit)
    keep = {key: request.GET[key] for key in ("forme",) if request.GET.get(key)}
    context = _search_page(request, evidences, form=form, keep=keep)
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


def _attestations_of(user, unit):
    tokens = Token.objects.select_related("passage__edition__work__author")
    queryset = (
        unit.attestations.active()
        .select_related("sense", "realization", "created_by")
        .prefetch_related(Prefetch("tokens", queryset=tokens))
    )
    attestations = []
    for attestation in _visible_parts(user, unit, queryset):
        attestation.quotation = quotation(list(attestation.tokens.all()))
        attestation.can_withdraw = can_withdraw_attestation(user, attestation)
        attestations.append(attestation)
    return sorted(
        attestations,
        key=lambda item: (item.status == Attestation.Status.REJECTED, not item.is_example),
    )


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
    return render(
        request,
        "phraseology/unit_detail.html",
        {
            "unit": unit,
            "edges": unit.edges,
            "senses": senses,
            "realizations": _visible_parts(user, unit, unit.realizations.active()),
            "attestations": _attestations_of(user, unit),
            "relations": _relations_of(user, unit),
            "references": _visible_parts(
                user, unit, unit.references.active().select_related("work")
            ),
            "can_edit": can_edit_unit(user, unit),
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
            return redirect(unit)
    return render(request, "phraseology/unit_edit.html", {"unit": unit, "form": form})


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
        request, "phraseology/part_form.html", {"unit": unit, "form": form, "heading": heading}
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
        {"unit": unit, "form": form, "heading": heading, "part": part, "kind": kind},
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


@login_required
@require_http_methods(["GET", "POST"])
def attestation_add(request, pk):
    unit = _editable_unit(request.user, pk)
    place = AttestationPlaceForm(request.POST or None, unit=unit)
    evidences, errors = _chosen_attestations(request)
    if request.method == "POST" and place.is_valid() and not errors:
        if evidences:
            created = add_attestations(
                unit,
                evidences,
                request.user,
                sense=place.cleaned_data["sense"],
                realization=place.cleaned_data["realization"],
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
    context = _search_page(request, evidences, unit=unit, place=place, errors=errors, keep={})
    return render(request, "phraseology/attestation_form.html", context)


@login_required
@require_POST
def attestation_withdraw(request, pk):
    attestation = get_object_or_404(Attestation.objects.active().select_related("unit"), pk=pk)
    unit = _unit(request.user, attestation.unit_id)
    attestation.unit = unit
    if not can_view(request.user, attestation):
        raise Http404
    try:
        withdraw_attestation(attestation, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("L’attestation est retirée ; elle reste dans l’historique."))
    return redirect(f"{unit.get_absolute_url()}#attestations")
