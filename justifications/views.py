from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from accounts.roles import is_reviewer
from corpus.search import quotation
from corpus.views import search_context
from moderation.registry import can_view
from phraseology.models import Attestation, Unit
from phraseology.spotting import spot_units, unit_attestations, visible_units
from translations.models import TranslatedSegment, TranslationVersion
from translations.permissions import can_challenge, can_translate
from translations.steps import sentence_at, shown_text

from .display import excerpt_parts, visible_evidences
from .forms import ChallengeCloseForm, ChallengeForm, JustificationForm, ReferenceFormSet
from .models import Challenge, Evidence, Justification
from .services import (
    add_evidences,
    attestation_evidence,
    close_challenge,
    corpus_evidence,
    create_challenge,
    create_justification,
    update_justification,
    withdraw_challenge,
    withdraw_evidence,
)

SEARCH_RESULTS = 20
CHALLENGES_PER_PAGE = 50
UNIT_ATTESTATIONS_SHOWN = 10
FORM_TEMPLATE = "justifications/justification_form.html"


def _hint(request):
    value = request.POST.get("debut") or request.GET.get("debut") or ""
    return int(value) if value.isdigit() else None


def _attestations(request):
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


def _references(request):
    data = request.POST if request.method == "POST" else None
    return ReferenceFormSet(data, prefix="references", form_kwargs={"user": request.user})


def _asked_unit(request):
    """The phraseological unit the justification was opened from, if the user may see it."""
    value = request.GET.get("unite", "")
    unit = Unit.objects.filter(pk=int(value)).first() if value.isdigit() else None
    return unit if unit is not None and can_view(request.user, unit) else None


def _unit_choices(user, translated, justification=None, asked=None):
    """Units a justification may cite: known in its sentence, already cited, or asked for."""
    _tokens, spots = spot_units(translated.text, user, describe=False)
    ids = {spot.unit.pk for spot in spots}
    if justification is not None:
        ids.update(justification.units.values_list("pk", flat=True))
    if asked is not None:
        ids.add(asked.pk)
    return visible_units(user).filter(pk__in=ids).order_by("reference_form")


def _unit_evidences(request):
    """Attestations of units ticked as evidence, among those the user may see."""
    if request.method != "POST":
        return []
    ids = [int(value) for value in request.POST.getlist("attestation_unite") if value.isdigit()]
    attestations = (
        Attestation.objects.active()
        .filter(pk__in=ids)
        .exclude(status=Attestation.Status.REJECTED)
        .select_related("unit")
    )
    return [attestation for attestation in attestations if can_view(request.user, attestation)]


def _reference_evidences(references):
    return [evidence for evidence in (form.evidence() for form in references) if evidence]


def _page_context(translated, latin=None, **extra):
    """``latin`` is the sentence as the reader sees it; by default the working text, which only
    the author of the version may see."""
    return {
        "version": translated.version,
        "segment": translated.segment,
        "translated": translated,
        "latin": translated.text if latin is None else latin,
        "source_language": translated.version.project.source_text.language,
        **extra,
    }


def _search_page_context(request, translated, evidences, **extra):
    """The corpus search of the page, and the attestations already ticked."""
    search = search_context(request, SEARCH_RESULTS)
    found = {hit.word_ids for hit in search.get("hits", [])}
    chosen = [quotation(evidence.tokens) for evidence in evidences]
    return _page_context(
        translated,
        search=search,
        chosen=[quote for quote in chosen if quote.word_ids not in found],
        chosen_ids={quote.word_ids for quote in chosen},
        hint=_hint(request),
        **extra,
    )


def _own_version(user, pk):
    version = get_object_or_404(
        TranslationVersion.objects.select_related("project__source_text", "author"), pk=pk
    )
    if not can_view(user, version):
        raise Http404
    if not can_translate(user, version):
        raise PermissionDenied
    return version


def _justification(user, pk):
    queryset = Justification.objects.select_related(
        "author",
        "translated_segment__segment",
        "translated_segment__version__project__source_text",
        "translated_segment__version__author",
    )
    justification = get_object_or_404(queryset, pk=pk)
    if not can_view(user, justification):
        raise Http404
    return justification


def _own_justification(user, pk):
    justification = _justification(user, pk)
    if user.pk != justification.author_id:
        raise PermissionDenied
    return justification


# Justifications


@login_required
@require_http_methods(["GET", "POST"])
def justification_create(request, version_pk, segment_pk):
    version = _own_version(request.user, version_pk)
    source_segment = get_object_or_404(version.project.source_text.segments, pk=segment_pk)
    translated = (
        TranslatedSegment.objects.filter(version=version, segment=source_segment)
        .exclude(text="")
        .first()
    )
    if translated is None:
        messages.error(request, _("Traduisez et enregistrez d’abord cette phrase."))
        return redirect("translations:version_edit", version.pk)
    translated.version, translated.segment = version, source_segment

    asked = _asked_unit(request)
    form = JustificationForm(
        request.POST or None,
        translated=translated,
        user=request.user,
        unit_choices=_unit_choices(request.user, translated, asked=asked),
        initial={
            "latin_excerpt": request.GET.get("extrait", ""),
            "units": [asked] if asked else [],
        },
    )
    references = _references(request)
    evidences, errors = _attestations(request)
    unit_evidences = _unit_evidences(request)
    if request.method == "POST":
        valid = form.is_valid() & references.is_valid()
        for message in errors:
            form.add_error(None, message)
        if valid and not errors:
            justification = form.save(commit=False)
            justification.translated_segment = translated
            all_evidences = (
                evidences
                + [attestation_evidence(attestation) for attestation in unit_evidences]
                + _reference_evidences(references)
            )
            units = form.cleaned_data.get("units", [])
            try:
                create_justification(
                    justification, request.user, all_evidences, _hint(request), units=units
                )
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("La justification est enregistrée."))
                return redirect(justification)
    keep = {key: request.GET[key] for key in ("extrait", "debut", "unite") if request.GET.get(key)}
    context = _search_page_context(
        request,
        translated,
        evidences,
        form=form,
        references=references,
        keep=keep,
        asked_unit=asked,
        unit_attestations=unit_attestations(asked, UNIT_ATTESTATIONS_SHOWN) if asked else [],
        chosen_unit_attestations={attestation.pk for attestation in unit_evidences},
        heading=_("Justifier un choix de traduction"),
        submit_label=_("Enregistrer la justification"),
        show_rules=True,
    )
    return render(request, FORM_TEMPLATE, context)


def justification_detail(request, pk):
    justification = _justification(request.user, pk)
    translated = justification.translated_segment
    justification.shown_text = shown_text(request.user, translated)
    challenges = [
        challenge
        for challenge in justification.challenges.select_related("author")
        if can_view(request.user, challenge)
    ]
    return render(
        request,
        "justifications/justification_detail.html",
        _page_context(
            translated,
            latin=justification.shown_text,
            justification=justification,
            evidences=visible_evidences(
                request.user, justification.evidences.all(), justification=justification
            ),
            parts=excerpt_parts(justification),
            can_edit=request.user.pk == justification.author_id,
            challenges=challenges,
            can_challenge=can_challenge(request.user, translated.version),
            units=[unit for unit in justification.units.all() if can_view(request.user, unit)],
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def justification_edit(request, pk):
    justification = _own_justification(request.user, pk)
    translated = justification.translated_segment
    hint = justification.latin_start
    form = JustificationForm(
        request.POST or None,
        instance=justification,
        translated=translated,
        user=request.user,
        unit_choices=_unit_choices(request.user, translated, justification=justification),
    )
    if request.method == "POST" and form.is_valid():
        units = form.cleaned_data.get("units")
        try:
            revision = update_justification(
                form.save(commit=False), request.user, hint, units=units
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if revision is None:
                messages.info(request, _("Aucune modification."))
            else:
                messages.success(request, _("Les modifications sont enregistrées."))
            return redirect(justification)
    context = _page_context(
        translated,
        form=form,
        justification=justification,
        heading=_("Modifier la justification"),
        submit_label=_("Enregistrer"),
        show_rules=True,
    )
    return render(request, FORM_TEMPLATE, context)


@login_required
@require_http_methods(["GET", "POST"])
def evidence_add(request, pk):
    justification = _own_justification(request.user, pk)
    translated = justification.translated_segment
    references = _references(request)
    evidences, errors = _attestations(request)
    if request.method == "POST" and references.is_valid() and not errors:
        new_evidences = evidences + _reference_evidences(references)
        if new_evidences:
            add_evidences(justification, new_evidences, request.user)
            count = len(new_evidences)
            messages.success(
                request,
                ngettext("%(count)d preuve ajoutée.", "%(count)d preuves ajoutées.", count)
                % {"count": count},
            )
            return redirect(justification)
        errors = [_("Cochez une attestation ou citez un ouvrage.")]
    context = _search_page_context(
        request,
        translated,
        evidences,
        references=references,
        justification=justification,
        errors=errors,
        keep={},
        heading=_("Ajouter des preuves"),
        submit_label=_("Ajouter les preuves"),
    )
    return render(request, FORM_TEMPLATE, context)


@login_required
@require_POST
def evidence_withdraw(request, pk):
    evidence = get_object_or_404(Evidence, pk=pk, justification__isnull=False)
    justification = _own_justification(request.user, evidence.justification_id)
    evidence.justification = justification
    try:
        withdraw_evidence(evidence, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La preuve est retirée."))
    return redirect(justification)


# Challenges


def _challenge(user, pk):
    queryset = Challenge.objects.select_related(
        "author",
        "closed_by",
        "justification",
        "step",
        "translated_segment__segment",
        "translated_segment__version__project__source_text",
        "translated_segment__version__author",
    )
    challenge = get_object_or_404(queryset, pk=pk)
    if not can_view(user, challenge):
        raise Http404
    return challenge


def challenge_list(request):
    open_first = Case(
        When(status=Challenge.Status.OPEN, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )
    challenges = (
        Challenge.objects.filter(
            is_hidden=False,
            translated_segment__version__state=TranslationVersion.State.PUBLISHED,
            translated_segment__version__is_hidden=False,
        )
        .select_related(
            "author", "translated_segment__version__project", "translated_segment__version__author"
        )
        .order_by(open_first, "-created_at", "-pk")
    )
    page = Paginator(challenges, CHALLENGES_PER_PAGE).get_page(request.GET.get("page"))
    return render(request, "justifications/challenge_list.html", {"page": page})


@login_required
@require_http_methods(["GET", "POST"])
def challenge_create(request, translated_pk):
    queryset = TranslatedSegment.objects.select_related(
        "segment", "version__project__source_text", "version__author"
    )
    translated = get_object_or_404(queryset, pk=translated_pk)
    if not can_view(request.user, translated.version):
        raise Http404
    if not can_challenge(request.user, translated.version):
        raise PermissionDenied
    # Only the text of the latest public step is contested, never the working text.
    latin = shown_text(request.user, translated)
    if not latin:
        raise Http404
    justification = None
    if request.GET.get("justification", "").isdigit():
        justification = get_object_or_404(
            translated.justifications.filter(is_hidden=False, step__isnull=False),
            pk=request.GET["justification"],
        )
    default_excerpt = request.GET.get("extrait") or (
        justification.latin_excerpt if justification else latin
    )
    form = ChallengeForm(
        request.POST or None,
        translated=translated,
        latin=latin,
        user=request.user,
        initial={"latin_excerpt": default_excerpt},
    )
    references = _references(request)
    evidences, errors = _attestations(request)
    if request.method == "POST":
        valid = form.is_valid() & references.is_valid()
        for message in errors:
            form.add_error(None, message)
        if valid and not errors:
            challenge = form.save(commit=False)
            challenge.translated_segment = translated
            challenge.justification = justification
            all_evidences = evidences + _reference_evidences(references)
            try:
                create_challenge(challenge, request.user, all_evidences, _hint(request))
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("La contestation est publiée."))
                return redirect(challenge)
    keep = {
        key: request.GET[key]
        for key in ("extrait", "debut", "justification")
        if request.GET.get(key)
    }
    context = _search_page_context(
        request,
        translated,
        evidences,
        latin=latin,
        form=form,
        references=references,
        keep=keep,
        justification=justification,
        heading=_("Contester un choix de traduction"),
        intro=_(
            "Exposez votre argument ; appuyez-le au besoin sur des contre-exemples du corpus ou "
            "sur des ouvrages de référence. L’auteur de la version pourra répondre et justifier "
            "son choix."
        ),
        submit_label=_("Publier la contestation"),
    )
    return render(request, FORM_TEMPLATE, context)


def challenge_detail(request, pk):
    user = request.user
    challenge = _challenge(user, pk)
    translated = challenge.translated_segment
    # The contested sentence as the contested step froze it.
    if challenge.step_id:
        challenge.shown_text = sentence_at(challenge.step, translated.segment_id)
    else:
        challenge.shown_text = shown_text(user, translated)
    justification = challenge.justification
    if justification is not None and not can_view(user, justification):
        justification = None
    return render(
        request,
        "justifications/challenge_detail.html",
        _page_context(
            translated,
            latin=challenge.shown_text,
            challenge=challenge,
            contested=justification,
            evidences=visible_evidences(user, challenge.evidences.all(), challenge=challenge),
            parts=excerpt_parts(challenge),
            close_form=ChallengeCloseForm() if challenge.is_open and is_reviewer(user) else None,
            can_withdraw=challenge.is_open and user.pk == challenge.author_id,
            can_justify=challenge.is_open and user.pk == translated.version.author_id,
        ),
    )


@login_required
@require_POST
def challenge_close(request, pk):
    challenge = _challenge(request.user, pk)
    if not is_reviewer(request.user):
        raise PermissionDenied
    form = ChallengeCloseForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choisissez une décision et motivez-la."))
        return redirect(challenge)
    data = form.cleaned_data
    try:
        close_challenge(challenge, request.user, data["decision"], data["resolution"])
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La contestation est close."))
    return redirect(challenge)


@login_required
@require_POST
def challenge_withdraw(request, pk):
    challenge = _challenge(request.user, pk)
    try:
        withdraw_challenge(challenge, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La contestation est retirée."))
    return redirect(challenge)
