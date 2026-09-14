from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("accounts.urls")),
    path("", include("moderation.urls")),
    path("", include("corpus.urls")),
    path("", include("translations.urls")),
    path("", include("justifications.urls")),
    path("", include("phraseology.urls")),
    path("", include("core.urls")),
]
