from django.urls import path

from . import views

app_name = "notebook"

urlpatterns = [
    path("carnet/", views.notebook, name="notebook"),
    path("carnet/surlignages/nouveau/", views.highlight_create, name="highlight_create"),
    path("carnet/surlignages/<int:pk>/retirer/", views.highlight_delete, name="highlight_delete"),
    path("carnet/notes/nouvelle/", views.note_create, name="note_create"),
    path("carnet/notes/<int:pk>/retirer/", views.note_delete, name="note_delete"),
    path("carnet/listes/ajouter/", views.list_add, name="list_add"),
    path("carnet/listes/<int:pk>/supprimer/", views.list_delete, name="list_delete"),
    path(
        "carnet/listes/passages/<int:pk>/retirer/",
        views.list_entry_delete,
        name="list_entry_delete",
    ),
]
