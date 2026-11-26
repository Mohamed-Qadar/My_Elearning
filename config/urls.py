from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Browsers also ask for /favicon.ico on their own; send them to the real icon.
    path("favicon.ico", RedirectView.as_view(url=static_url("images/favicon.svg"))),
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),  # the language switch posts here
    path("accounts/", include("accounts.urls")),
    path("student/", include("learning.urls")),
    path("", include("courses.urls")),
    path("", include("core.urls")),
]

# Serve uploaded files during development only.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
