"""Pages where versions work together: update a copy from its original, propose to the original,
review proposals, label and restore steps, the network of copies, who wrote what."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import check_text_for_links
from moderation.registry import can_view
from moderation.services import save_with_revision

from .diffs import word_diff
from .forms import (
    ProposalForm,
    ProposalReviewForm,
    StepLabelForm,
    TmxImportForm,
    XliffImportForm,
)
from .models import (
    ChangeProposal,  # noqa: F401 - the form builds one
    PersonalMemoryEntry,
)
from .network import copy_network
from .permissions import can_propose
from .services import create_proposal, review_proposal, save_translation, set_sentence_status
from .sources import SourceHistory
from .sync import (
    differences_with_original,
    restore_preview,
    restore_step,
    take_upstream,
    upstream_changes,
)
from .views import _contribute, _export_step, _own_version, _proposal, _rows, _version
from .xliff import MAX_BYTES, STATUSES, XliffError, parse_tmx, parse_xliff

TMX_MAX_BYTES = 5 * 1024 * 1024
PERSONAL_MEMORY_LIMIT = 20000


@login_required
@require_http_methods(["GET", "POST"])
def sync_copy(request, pk):
    """What the original changed since the copy, to take sentence by sentence."""
    version = _own_version(request.user, pk)
    if version.copied_from_id is None:
        messages.info(request, _("Cette version n’est pas une copie."))
        return redirect(version)
    latest, changes = upstream_changes(request.user, version)
    if request.method == "POST":
        chosen = {int(value) for value in request.POST.getlist("phrase") if value.isdigit()}
        taken = take_upstream(request.user, version, chosen)
        messages.success(
            request,
            ngettext(
                "%(count)d phrase reprise de l’originale.",
                "%(count)d phrases reprises de l’originale.",
                taken,
            )
            % {"count": taken},
        )
        return redirect("translations:version_edit", version.pk)
    return render(
        request,
        "translations/sync_copy.html",
        {
            "version": version,
            "project": version.project,
            "original": version.copied_from.version,
            "base": version.synced_to or version.copied_from,
            "latest": latest,
            "changes": changes,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def propose_to_original(request, pk):
    """Prepare a proposal to the original with the sentences where the copy differs."""
    user = request.user
    version = _own_version(user, pk)
    if version.copied_from_id is None:
        messages.info(request, _("Cette version n’est pas une copie."))
        return redirect(version)
    original = version.copied_from.version
    if not can_propose(user, original) or not can_view(user, original):
        messages.error(request, _("Vous ne pouvez pas proposer de modifications à l’originale."))
        return redirect(version)
    step, rows = differences_with_original(user, version)
    form = ProposalForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        chosen = set(request.POST.getlist("phrase"))
        texts = {
            segment: mine for segment, _n, _theirs, mine, _c in rows if str(segment.pk) in chosen
        }
        proposal = form.save(commit=False)
        proposal.version = original
        try:
            proposal, saved = _contribute(request, create_proposal, proposal, user, texts)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if saved:
                messages.success(
                    request, _("La proposition est envoyée à l’auteur de l’originale.")
                )
                return redirect(proposal)
    return render(
        request,
        "translations/propose_to_original.html",
        {
            "version": version,
            "project": version.project,
            "original": original,
            "step": step,
            "rows": rows,
            "form": form,
        },
    )


@login_required
@require_POST
def proposal_review(request, pk):
    """Approve a proposal, request changes or comment on it."""
    proposal = _proposal(request.user, pk)
    form = ProposalReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choisissez un avis."))
        return redirect(proposal)
    try:
        check_text_for_links(request.user, form.cleaned_data["text"])
        _review, saved = _contribute(
            request,
            review_proposal,
            proposal,
            request.user,
            form.cleaned_data["verdict"],
            form.cleaned_data["text"],
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if saved:
            messages.success(request, _("Votre relecture est publiée."))
    return redirect(f"{proposal.get_absolute_url()}#relectures")


@login_required
@require_POST
def step_label(request, pk, number):
    """Name a step, like a release; an empty name takes the label away."""
    version = _own_version(request.user, pk)
    step = get_object_or_404(version.steps, number=number)
    step.version = version
    form = StepLabelForm(request.POST, instance=step, user=request.user)
    if form.is_valid():
        revision = save_with_revision(form.save(commit=False), request.user)
        messages.success(
            request, _("L’étiquette est enregistrée.") if revision else _("Aucune modification.")
        )
    else:
        messages.error(request, " ".join(form.errors.get("label", [])))
    return redirect(step)


@login_required
@require_http_methods(["GET", "POST"])
def step_restore(request, pk, number):
    """Show what going back to a step would change in the working text, then do it."""
    version = _own_version(request.user, pk)
    step = get_object_or_404(version.steps, number=number)
    step.version = version
    if request.method == "POST":
        count = restore_step(request.user, version, step)
        messages.success(
            request,
            ngettext(
                "%(count)d phrase revient au texte de l’étape. Créez une étape pour le publier.",
                "%(count)d phrases reviennent au texte de l’étape. Créez une étape pour le "
                "publier.",
                count,
            )
            % {"count": count},
        )
        return redirect("translations:version_edit", version.pk)
    return render(
        request,
        "translations/step_restore.html",
        {
            "version": version,
            "project": version.project,
            "step": step,
            "rows": restore_preview(version, step),
        },
    )


def version_network(request, pk):
    """The versions this one comes from, and the tree of the copies made from it."""
    version = _version(request.user, pk)
    ancestors, nodes = copy_network(request.user, version)
    return render(
        request,
        "translations/version_network.html",
        {"version": version, "project": version.project, "ancestors": ancestors, "nodes": nodes},
    )


WRITER_COLORS = 8


def version_blame(request, pk):
    """Each sentence of the text the user sees, marked with who wrote it, like git blame."""
    version = _version(request.user, pk)
    step = _export_step(request, version)
    step, rows = _rows(request.user, version, step)
    order, counts = {}, {}
    for row in rows:
        sentence = row["sentence"]
        if not row["saved"]:
            row["writer"] = None
            continue
        writer = getattr(sentence, "written_by", None) or version.author
        order.setdefault(writer.pk, (len(order) % WRITER_COLORS, writer))
        counts[writer.pk] = counts.get(writer.pk, 0) + 1
        row["writer"] = writer
        row["color"] = order[writer.pk][0]
    total = sum(counts.values()) or 1
    legend = [
        {
            "user": writer,
            "color": color,
            "count": counts[pk],
            "percent": round(counts[pk] * 100 / total),
        }
        for pk, (color, writer) in order.items()
    ]
    return render(
        request,
        "translations/version_blame.html",
        {
            "version": version,
            "project": version.project,
            "step": step,
            "rows": rows,
            "legend": legend,
        },
    )


XLIFF_SESSION = "xliff_import_{pk}"


@login_required
@require_http_methods(["GET", "POST"])
def xliff_import(request, pk):
    """Import an XLIFF file into the working text: read it, show the sentences it changes,
    then apply the ones kept."""
    version = _own_version(request.user, pk)
    key = XLIFF_SESSION.format(pk=version.pk)
    form = XliffImportForm()
    history = SourceHistory(version.project.source_text)
    segments = {
        str(segment.pk): (number, segment)
        for number, segment in enumerate(history.segments_at(), 1)
    }
    working = {str(item.segment_id): item.text for item in version.segments.current()}
    if request.method == "POST" and request.POST.get("action") == "appliquer":
        pending = request.session.pop(key, {})
        chosen = set(request.POST.getlist("phrase"))
        keep_status = bool(request.POST.get("statuts"))
        done = 0
        with transaction.atomic():
            for segment_id, (text, state) in pending.items():
                if segment_id not in chosen or segment_id not in segments:
                    continue
                segment = segments[segment_id][1]
                save_translation(version, segment, text, request.user)
                status = STATUSES.get(state)
                if keep_status and status and text:
                    set_sentence_status(version, segment, status, request.user)
                done += 1
        messages.success(
            request,
            ngettext("%(count)d phrase importée.", "%(count)d phrases importées.", done)
            % {"count": done},
        )
        return redirect("translations:version_edit", version.pk)
    rows, unknown = [], 0
    if request.method == "POST":
        form = XliffImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                units = parse_xliff(form.cleaned_data["file"].read(MAX_BYTES + 1))
            except XliffError as error:
                form.add_error("file", str(error))
            else:
                pending = {}
                for unit in units:
                    if unit.id not in segments:
                        unknown += 1
                        continue
                    current = working.get(unit.id, "")
                    if unit.target and unit.target != current:
                        number, segment = segments[unit.id]
                        pending[unit.id] = [unit.target, unit.state]
                        rows.append(
                            {
                                "segment": segment,
                                "number": number,
                                "state": unit.state,
                                "chunks": word_diff(current, unit.target),
                            }
                        )
                request.session[key] = pending
    return render(
        request,
        "translations/xliff_import.html",
        {
            "version": version,
            "project": version.project,
            "form": form,
            "rows": sorted(rows, key=lambda row: row["number"]),
            "unknown": unknown,
            "read": request.method == "POST" and form.is_valid() and not form.errors,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def personal_memory(request):
    """One's own translation memory: import a TMX file, see how many pairs, erase them all."""
    user = request.user
    entries = PersonalMemoryEntry.objects.filter(user=user)
    form = TmxImportForm()
    if request.method == "POST" and request.POST.get("action") == "effacer":
        entries.delete()
        messages.success(request, _("Votre mémoire personnelle est effacée."))
        return redirect("translations:personal_memory")
    if request.method == "POST":
        form = TmxImportForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                pairs = parse_tmx(upload.read(TMX_MAX_BYTES + 1), TMX_MAX_BYTES)
            except XliffError as error:
                form.add_error("file", str(error))
            else:
                room = max(0, PERSONAL_MEMORY_LIMIT - entries.count())
                known = set(entries.values_list("source", "latin"))
                new = [
                    PersonalMemoryEntry(
                        user=user,
                        language=language,
                        source=source[:4000],
                        latin=latin[:4000],
                        origin=upload.name[:200],
                    )
                    for language, source, latin in pairs
                    if (source, latin) not in known
                ][:room]
                PersonalMemoryEntry.objects.bulk_create(new)
                messages.success(
                    request,
                    ngettext(
                        "%(count)d paire ajoutée à votre mémoire.",
                        "%(count)d paires ajoutées à votre mémoire.",
                        len(new),
                    )
                    % {"count": len(new)},
                )
                return redirect("translations:personal_memory")
    return render(
        request,
        "translations/personal_memory.html",
        {
            "form": form,
            "count": entries.count(),
            "limit": PERSONAL_MEMORY_LIMIT,
            "files": entries.values("origin").annotate(total=Count("pk")).order_by("origin"),
        },
    )
