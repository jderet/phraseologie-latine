from django.urls import path

from . import views

app_name = "justifications"

urlpatterns = [
    path(
        "versions/<int:version_pk>/phrases/<int:segment_pk>/justifier/",
        views.justification_create,
        name="create",
    ),
    path("justifications/<int:pk>/", views.justification_detail, name="detail"),
    path("justifications/<int:pk>/modifier/", views.justification_edit, name="edit"),
    path("justifications/<int:pk>/preuves/", views.evidence_add, name="evidence_add"),
    path("preuves/<int:pk>/retirer/", views.evidence_withdraw, name="evidence_withdraw"),
    path(
        "phrases/<int:translated_pk>/contester/",
        views.challenge_create,
        name="challenge_create",
    ),
    path("contestations/", views.challenge_list, name="challenge_list"),
    path("contestations/<int:pk>/", views.challenge_detail, name="challenge"),
    path("contestations/<int:pk>/cloture/", views.challenge_close, name="challenge_close"),
    path("contestations/<int:pk>/retrait/", views.challenge_withdraw, name="challenge_withdraw"),
]
