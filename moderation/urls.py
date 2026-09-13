from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path(
        "historique/<slug:app_label>/<slug:model_name>/<int:pk>/",
        views.history,
        name="history",
    ),
    path("historique/revision/<int:pk>/retablir/", views.revert, name="revert"),
    path(
        "signaler/<slug:app_label>/<slug:model_name>/<int:pk>/",
        views.report,
        name="report",
    ),
    path("moderation/signalements/", views.report_queue, name="report_queue"),
    path(
        "moderation/signalements/<int:pk>/traiter/",
        views.handle_report,
        name="handle_report",
    ),
]
