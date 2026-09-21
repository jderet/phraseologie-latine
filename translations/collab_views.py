"""Pages around a translation: label and restore steps, who wrote what, XLIFF and TMX."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from moderation.services import save_with_revision

from .diffs import word_diff
from .forms import StepLabelForm, TmxImportForm, XliffImportForm
from .models import PersonalMemoryEntry
from .restore import restore_preview, restore_step
from .services import save_translation, set_sentence_status
from .sources import SourceHistory
from .views import _export_step, _own_version, _rows, _version
from .xliff import MAX_BYTES, STATUSES, XliffError, parse_tmx, parse_xliff

TMX_MAX_BYTES = 5 * 1024 * 1024
PERSONAL_MEMORY_LIMIT = 20000


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
