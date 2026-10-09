from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Attendee


def admin_required(view):
    """Admin-only views 404 for everyone else so the admin area isn't discoverable."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not getattr(request, "is_admin", False):
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper


def is_owner(request, attendee):
    return attendee is not None and attendee.token == request.attendee_token


def can_edit(request, attendee):
    """Admins may edit anything; attendees may edit only their own profile and claims."""
    return getattr(request, "is_admin", False) or is_owner(request, attendee)


def ensure_can_edit(request, attendee):
    if not can_edit(request, attendee):
        raise PermissionDenied


def current_attendee(request, event):
    """The requesting browser's profile for this event, or None if they haven't signed up yet."""
    return Attendee.objects.filter(event=event, token=request.attendee_token).first()
