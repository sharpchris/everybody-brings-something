from django.urls import include, path

from events.views.health import health

urlpatterns = [
    path("health/", health, name="health"),
    path("manage/", include("events.urls_manage")),
    # Public routes last: they include the catch-all /<slug>/.
    path("", include("events.urls_public")),
]
