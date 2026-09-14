from django.urls import path

from . import views

app_name = "corpus"

urlpatterns = [
    path("recherche/", views.search, name="search"),
    path("recherche/extrait/", views.search_fragment, name="search_fragment"),
    path("corpus/", views.index, name="index"),
    path("corpus/mots/<int:pk>/corriger/", views.correction_create, name="correction_create"),
    path("corrections/", views.correction_list, name="corrections"),
    path("corrections/<int:pk>/examen/", views.correction_review, name="correction_review"),
    path("corpus/<str:work_id>/", views.work_detail, name="work"),
    path("corpus/<str:work_id>/lecture/", views.reading, name="reading"),
    path("corpus/<str:work_id>/lecture/<str:part>/", views.reading, name="reading_part"),
    path("corpus/<str:work_id>/<str:reference>/", views.passage_detail, name="passage"),
]
