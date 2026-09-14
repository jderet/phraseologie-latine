from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("mentions-legales/", views.legal_notice, name="legal_notice"),
    path("confidentialite/", views.privacy, name="privacy"),
    path("conditions-utilisation/", views.terms, name="terms"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path(".well-known/tdmrep.json", views.tdmrep, name="tdmrep"),
]
