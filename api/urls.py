from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("api/v1/", views.index, name="index"),
    path("api/v1/fiches/", views.units, name="units"),
    path("api/v1/fiches/<int:pk>/", views.unit, name="unit"),
    path("api/v1/neologismes/", views.neologisms, name="neologisms"),
    path("api/v1/neologismes/<int:pk>/", views.neologism, name="neologism"),
    path("api/v1/versions/", views.versions, name="versions"),
    path("api/v1/versions/<int:pk>/", views.version, name="version"),
    path("api/v1/recherches-infructueuses/", views.negative_searches, name="negative_searches"),
    path("donnees/", views.data, name="data"),
    path("donnees/export/", views.export_download, name="export"),
]
