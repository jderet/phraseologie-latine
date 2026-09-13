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
    path(
        "projets/<int:project_pk>/nouvelle-version/",
        views.version_create,
        name="version_create",
    ),
    path("versions/<int:pk>/", views.version_detail, name="version"),
    path("versions/<int:pk>/traduire/", views.version_edit, name="version_edit"),
    path("versions/<int:pk>/style/", views.version_settings, name="version_settings"),
    path("versions/<int:pk>/publier/", views.version_publish, name="version_publish"),
]
