from django.urls import path

from . import views

app_name = "translations"

urlpatterns = [
    path("textes/", views.source_list, name="source_list"),
    path("textes/ajouter/", views.source_create, name="source_create"),
    path("textes/<int:pk>/", views.source_detail, name="source"),
    path("textes/<int:pk>/modifier/", views.source_edit, name="source_edit"),
    path("textes/<int:source_pk>/nouveau-projet/", views.project_create, name="project_create"),
    path("projets/", views.project_list, name="project_list"),
    path("projets/<int:pk>/", views.project_detail, name="project"),
    path("projets/<int:pk>/modifier/", views.project_edit, name="project_edit"),
    path("projets/<int:pk>/comparer/", views.project_compare, name="project_compare"),
    path("projets/<int:pk>/reference/", views.project_reference, name="project_reference"),
    path(
        "projets/<int:project_pk>/nouvelle-version/",
        views.version_create,
        name="version_create",
    ),
    path("versions/<int:pk>/", views.version_detail, name="version"),
    path("versions/<int:pk>/traduire/", views.version_edit, name="version_edit"),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/",
        views.translation_save,
        name="translation_save",
    ),
    path("versions/<int:pk>/etapes/", views.step_list, name="step_list"),
    path("versions/<int:pk>/etapes/nouvelle/", views.step_create, name="step_create"),
    path("versions/<int:pk>/etapes/comparer/", views.step_compare, name="step_compare"),
    path("versions/<int:pk>/etapes/<int:number>/", views.step_detail, name="step"),
    path("versions/<int:pk>/etapes/<int:number>/copier/", views.version_copy, name="version_copy"),
    path("versions/<int:pk>/style/", views.version_settings, name="version_settings"),
    path("versions/<int:pk>/publier/", views.version_publish, name="version_publish"),
    path(
        "versions/<int:pk>/export/bilingue.txt",
        views.version_export_text,
        name="version_export_text",
    ),
    path(
        "versions/<int:pk>/export/version.tei.xml",
        views.version_export_tei,
        name="version_export_tei",
    ),
    path(
        "versions/<int:pk>/export/version.tmx", views.version_export_tmx, name="version_export_tmx"
    ),
    path(
        "versions/<int:pk>/export/imprimer/",
        views.version_export_print,
        name="version_export_print",
    ),
]
