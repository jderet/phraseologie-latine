"""The private notebook of a reader: its page, and the panels that add to it from the reading.

Every object is looked up with its owner, so that nobody reaches another reader's notebook.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from corpus.models import Passage, Token
from corpus.search import quotation
from justifications.services import corpus_evidence

from .forms import HighlightForm, ListForm, NoteForm
from .models import Highlight, PassageList, PassageListEntry, PrivateNote
from .services import add_highlight, add_private_note, add_to_list

SHOWN = 200


def _back(request):
    url = request.POST.get("next") or request.GET.get("retour") or ""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return reverse("notebook:notebook")


def _reading_url(passage):
    reading = reverse("corpus:reading", args=[passage.edition.work.cts_id])
    return f"{reading}?{urlencode({'aller': passage.reference})}"


def _quoted(items):
    items = list(items)
    for item in items:
        item.quotation = quotation(list(item.tokens.all()))
        item.reading_url = _reading_url(item.passage)
    return items


@login_required
def notebook(request):
    """Everything the reader kept, with links to the passages."""
    user = request.user
    words = Prefetch("tokens", queryset=Token.objects.order_by("position"))
    passage = "passage__edition__work__author"
    entries = PassageListEntry.objects.select_related(passage)
    lists = list(user.passage_lists.prefetch_related(Prefetch("entries", queryset=entries)))
    for passage_list in lists:
        for entry in passage_list.entries.all():
            entry.reading_url = _reading_url(entry.passage)
    return render(
        request,
        "notebook/notebook.html",
        {
            "highlights": _quoted(
                user.highlights.select_related(passage).prefetch_related(words)[:SHOWN]
            ),
            "notes": _quoted(
                user.private_notes.select_related(passage).prefetch_related(words)[:SHOWN]
            ),
            "lists": lists,
        },
    )


def _panel(request, template, context):
    """A panel of the reading, or without script a page of its own."""
    if request.GET.get("fragment") == "1":
        return render(request, template, context)
    return render(request, "notebook/panel_page.html", {**context, "panel_template": template})


def _words_panel(request, template, words, form):
    back = _back(request)
    try:
        evidence = corpus_evidence(words)
    except ValidationError as error:
        return _panel(request, template, {"errors": error.messages, "back": back})
    context = {
        "quote": quotation(evidence.tokens),
        "words": ",".join(str(token.pk) for token in evidence.tokens),
        "back": back,
        "form": form,
    }
    return _panel(request, template, context)


@login_required
@require_http_methods(["GET", "POST"])
def highlight_create(request):
    words = request.POST.get("words") or request.GET.get("mots", "")
    form = HighlightForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                add_highlight(request.user, words, form.cleaned_data["color"])
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, _("Les mots sont surlignés dans votre carnet."))
        return redirect(_back(request))
    return _words_panel(request, "notebook/highlight_panel.html", words, form)


@login_required
@require_http_methods(["GET", "POST"])
def note_create(request):
    words = request.POST.get("words") or request.GET.get("mots", "")
    form = NoteForm(request.POST or None)
    if request.method == "POST":
        if not form.is_valid():
            messages.error(request, _("Écrivez la note."))
        else:
            try:
                add_private_note(request.user, words, form.cleaned_data["text"])
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, _("La note est dans votre carnet."))
        return redirect(_back(request))
    return _words_panel(request, "notebook/note_panel.html", words, form)


@login_required
@require_http_methods(["GET", "POST"])
def list_add(request):
    value = request.POST.get("passage") or request.GET.get("passage", "")
    passage = get_object_or_404(
        Passage.objects.select_related("edition__work__author"),
        pk=int(value) if value.isdigit() else 0,
    )
    form = ListForm(request.POST or None, user=request.user)
    if request.method == "POST":
        if not form.is_valid():
            messages.error(request, _("Choisissez une liste ou nommez-en une nouvelle."))
        else:
            try:
                entry = add_to_list(request.user, passage, form.cleaned_data["list_name"])
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(
                    request,
                    _("Le passage est dans la liste « %(name)s ».")
                    % {"name": entry.passage_list.name},
                )
        return redirect(_back(request))
    context = {"passage": passage, "form": form, "back": _back(request)}
    return _panel(request, "notebook/list_panel.html", context)


@login_required
@require_POST
def highlight_delete(request, pk):
    get_object_or_404(Highlight, pk=pk, owner=request.user).delete()
    messages.success(request, _("Le surlignage est retiré de votre carnet."))
    return redirect(_back(request))


@login_required
@require_POST
def note_delete(request, pk):
    get_object_or_404(PrivateNote, pk=pk, owner=request.user).delete()
    messages.success(request, _("La note est retirée de votre carnet."))
    return redirect(_back(request))


@login_required
@require_POST
def list_delete(request, pk):
    get_object_or_404(PassageList, pk=pk, owner=request.user).delete()
    messages.success(request, _("La liste est supprimée de votre carnet."))
    return redirect(_back(request))


@login_required
@require_POST
def list_entry_delete(request, pk):
    get_object_or_404(PassageListEntry, pk=pk, passage_list__owner=request.user).delete()
    messages.success(request, _("Le passage est retiré de la liste."))
    return redirect(_back(request))
