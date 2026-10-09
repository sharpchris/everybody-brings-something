"""Template context available on every page."""

from .models import SITE_NAME


def site(request):
    site_settings = getattr(request, "site", None)
    return {
        "is_admin": getattr(request, "is_admin", False),
        "guest_view": getattr(request, "guest_view", False),
        "site": site_settings,
        "site_title": site_settings.title if site_settings else SITE_NAME,
    }
