from django.urls import path

from . import views

app_name = "activity"

urlpatterns = [
    path("notifications/", views.notification_list, name="notifications"),
    path("notifications/tout-lu/", views.notifications_read, name="notifications_read"),
    path("notifications/<int:pk>/", views.notification_open, name="notification"),
]
