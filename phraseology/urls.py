from django.urls import path

from . import views

app_name = "phraseology"

urlpatterns = [
    path("fiches/", views.unit_list, name="unit_list"),
    path("fiches/nouvelle/", views.unit_create, name="unit_create"),
    path("fiches/<int:pk>/", views.unit_detail, name="unit"),
    path("fiches/<int:pk>/modifier/", views.unit_edit, name="unit_edit"),
    path("fiches/<int:pk>/frequence/", views.unit_frequency, name="unit_frequency"),
    path("fiches/<int:pk>/proposer/", views.unit_propose, name="unit_propose"),
    path("fiches/<int:pk>/valider/", views.unit_validate, name="unit_validate"),
    path("fiches/<int:pk>/contester/", views.unit_contest, name="unit_contest"),
    path("fiches/<int:pk>/lever/", views.unit_resolve, name="unit_resolve"),
    path("fiches/<int:pk>/attestations/", views.attestation_add, name="attestation_add"),
    path("fiches/<int:pk>/ajouter/<slug:kind>/", views.part_create, name="part_create"),
    path("fiches/elements/<slug:kind>/<int:pk>/", views.part_edit, name="part_edit"),
    path(
        "fiches/elements/<slug:kind>/<int:pk>/retirer/",
        views.part_withdraw,
        name="part_withdraw",
    ),
    path(
        "attestations/<int:pk>/retirer/",
        views.attestation_withdraw,
        name="attestation_withdraw",
    ),
    path("attestations/<int:pk>/examen/", views.attestation_review, name="attestation_review"),
    path("attestations/<int:pk>/exemple/", views.attestation_example, name="attestation_example"),
]
