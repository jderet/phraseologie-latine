from django.urls import path

from . import views

app_name = "corpus"

urlpatterns = [
    path("recherche/", views.search, name="search"),
    path("corpus/", views.index, name="index"),
    path("corpus/<str:work_id>/", views.work_detail, name="work"),
    path("corpus/<str:work_id>/<str:reference>/", views.passage_detail, name="passage"),
]
