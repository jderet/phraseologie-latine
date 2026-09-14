"""The public API: read-only JSON of the public data, and the open data page (Q65)."""

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from corpus.search import corpus_version

from . import serializers
from .export import latest_export

PAGE_SIZE = 100


def _json(data, status=200):
    response = JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})
    # Public, read-only data that any site may read; no cookie is used.
    response["Access-Control-Allow-Origin"] = "*"
    return response


def _not_found():
    return _json({"error": "not found"}, status=404)


def _list(request, queryset, serialize):
    paginator = Paginator(queryset, PAGE_SIZE)
    try:
        page = paginator.page(request.GET.get("page") or 1)
    except (EmptyPage, PageNotAnInteger):
        return _not_found()
    base = request.build_absolute_uri(request.path)
    link = request.build_absolute_uri
    return _json(
        {
            "license": serializers.LICENSE,
            "count": paginator.count,
            "next": f"{base}?page={page.next_page_number()}" if page.has_next() else None,
            "previous": (
                f"{base}?page={page.previous_page_number()}" if page.has_previous() else None
            ),
            "results": [serialize(item, link) for item in page.object_list],
        }
    )


def _detail(request, queryset, pk, serialize):
    item = queryset.filter(pk=pk).first()
    if item is None or not serializers.visible(item):
        return _not_found()
    return _json({"license": serializers.LICENSE, **serialize(item, request.build_absolute_uri)})


@require_GET
def index(request):
    link = request.build_absolute_uri
    return _json(
        {
            "name": "Phraséologie latine",
            "license": serializers.LICENSE,
            "license_url": serializers.LICENSE_URL,
            "corpus_version": corpus_version().label,
            "endpoints": {
                "units": link(reverse("api:units")),
                "neologisms": link(reverse("api:neologisms")),
                "versions": link(reverse("api:versions")),
                "negative_searches": link(reverse("api:negative_searches")),
                "sightings": link(reverse("api:sightings")),
                "reading_notes": link(reverse("api:reading_notes")),
                "corrections": link(reverse("api:corrections")),
            },
            "full_export": link(reverse("api:data")),
        }
    )


@require_GET
def units(request):
    return _list(request, serializers.public_units(), serializers.unit_summary)


@require_GET
def unit(request, pk):
    return _detail(request, serializers.public_units(), pk, serializers.unit_data)


@require_GET
def neologisms(request):
    return _list(request, serializers.public_neologisms(), serializers.neologism_summary)


@require_GET
def neologism(request, pk):
    return _detail(request, serializers.public_neologisms(), pk, serializers.neologism_data)


@require_GET
def versions(request):
    return _list(request, serializers.public_versions(), serializers.version_summary)


@require_GET
def version(request, pk):
    return _detail(request, serializers.public_versions(), pk, serializers.version_data)


@require_GET
def negative_searches(request):
    return _list(request, serializers.public_negative_searches(), serializers.negative_search_data)


@require_GET
def sightings(request):
    return _list(request, serializers.public_sightings(), serializers.sighting_data)


@require_GET
def reading_notes(request):
    return _list(request, serializers.public_reading_notes(), serializers.reading_note_data)


@require_GET
def corrections(request):
    return _list(request, serializers.validated_corrections(), serializers.correction_data)


@require_GET
def data(request):
    return render(
        request,
        "api/data.html",
        {"export": latest_export(), "api_url": request.build_absolute_uri(reverse("api:index"))},
    )


@require_GET
def export_download(request):
    export = latest_export()
    if export is None:
        raise Http404
    return FileResponse(export.path.open("rb"), as_attachment=True, filename=export.path.name)
