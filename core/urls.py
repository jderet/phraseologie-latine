from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("apparence/", views.theme, name="theme"),
    path("mentions-legales/", views.legal_notice, name="legal_notice"),
    path("confidentialite/", views.privacy, name="privacy"),
    path("conditions-utilisation/", views.terms, name="terms"),
    path("guide/", views.guide, name="guide"),
    path("guide/versions/<int:number>/", views.guide, name="guide_version"),
    path("guide/publier/", views.guide_publish, name="guide_publish"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path(".well-known/tdmrep.json", views.tdmrep, name="tdmrep"),
]
