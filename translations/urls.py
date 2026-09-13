from django.urls import path

from . import views

app_name = "translations"

urlpatterns = [
    path("textes/", views.source_list, name="source_list"),
    path("textes/ajouter/", views.source_create, name="source_create"),
    path("textes/<int:pk>/", views.source_detail, name="source"),
    path("textes/<int:pk>/modifier/", views.source_edit, name="source_edit"),
]
