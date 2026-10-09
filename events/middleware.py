"""Request middleware: attendee cookie, admin key, and site settings (time zone)."""

import hmac
import logging
import uuid
import zoneinfo
from urllib.parse import quote, urlencode

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponseRedirect
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils import timezone
from django.utils.http import escape_leading_slashes

from .models import SiteSettings

logger = logging.getLogger(__name__)

ATTENDEE_COOKIE_SALT = "events.attendee"
# Healthchecks hit this every few seconds; they need neither a cookie nor site settings.
HEALTH_PATH = "/health/"


class AttendeeCookieMiddleware:
    """Gives every browser a stable, signed UUID so attendees can edit their own signups."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        name = settings.ATTENDEE_COOKIE_NAME
        token = None
        raw = request.get_signed_cookie(name, default=None, salt=ATTENDEE_COOKIE_SALT)
        if raw:
            try:
                token = uuid.UUID(raw)
            except ValueError:
                token = None
        is_new = token is None
        if is_new:
            token = uuid.uuid4()
        request.attendee_token = token

        response = self.get_response(request)

        if is_new and request.path != HEALTH_PATH:
            response.set_signed_cookie(
                name,
                str(token),
                salt=ATTENDEE_COOKIE_SALT,
                max_age=settings.ATTENDEE_COOKIE_AGE,
                httponly=True,
                samesite="Lax",
                secure=settings.HTTPS,
            )
        return response


def admin_fingerprint():
    """Ties admin sessions to the current key: rotating or clearing ADMIN_KEY revokes them all."""
    return salted_hmac("events.admin", settings.ADMIN_KEY).hexdigest()


class AdminKeyMiddleware:
    """`?admin=<ADMIN_KEY>` unlocks admin mode in the session, then strips the key from the URL."""

    SESSION_KEY = "admin_fp"
    GUEST_VIEW_KEY = "guest_view"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.GET.get("admin")
        if supplied is not None:
            expected = settings.ADMIN_KEY.encode()
            # A "+" in an unencoded link arrives as a space, so accept that spelling too.
            candidates = {supplied, supplied.replace(" ", "+")}
            if expected and any(hmac.compare_digest(c.encode(), expected) for c in candidates):
                request.session[self.SESSION_KEY] = admin_fingerprint()
                request.session.cycle_key()
            remaining = request.GET.copy()
            remaining.pop("admin", None)
            query = urlencode(remaining, doseq=True)
            # Re-quote and escape so a path like //evil.example can't become an off-site redirect.
            path = escape_leading_slashes(quote(request.path))
            return HttpResponseRedirect(path + (f"?{query}" if query else ""))

        stored = request.session.get(self.SESSION_KEY)
        request.is_real_admin = bool(
            settings.ADMIN_KEY and stored and constant_time_compare(stored, admin_fingerprint())
        )
        # Guest view: an admin sees the site exactly as attendees do until they exit it.
        request.guest_view = request.is_real_admin and bool(request.session.get(self.GUEST_VIEW_KEY))
        request.is_admin = request.is_real_admin and not request.guest_view
        return self.get_response(request)


class SiteSettingsMiddleware:
    """Loads the site settings once per request and renders times in their time zone."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_PATH:
            # Let the health view run its own DB check and report 503 if the DB is down.
            return self.get_response(request)
        try:
            request.site = SiteSettings.load()
        except DatabaseError:
            logger.exception("Couldn't load site settings; using defaults")
            request.site = SiteSettings()
        try:
            timezone.activate(zoneinfo.ZoneInfo(request.site.time_zone))
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            timezone.deactivate()  # fall back to settings.TIME_ZONE
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
