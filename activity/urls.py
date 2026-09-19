from django.urls import path

from . import views

app_name = "activity"

urlpatterns = [
    path("atelier/", views.workshop, name="workshop"),
    path("notifications/", views.notification_list, name="notifications"),
    path("notifications/tout-lu/", views.notifications_read, name="notifications_read"),
    path("notifications/<int:pk>/", views.notification_open, name="notification"),
    path(
        "suivre/<slug:app_label>/<slug:model_name>/<int:pk>/",
        views.follow_toggle,
        name="follow",
    ),
    path("versions/<int:pk>/etoile/", views.star_toggle, name="star"),
]
