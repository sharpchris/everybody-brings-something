"""Shared context for rendering an event's signup sheet (used by public and admin views)."""

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from ..models import Claim, FieldValue, Item, Category
from ..permissions import current_attendee

_UNSET = object()


def claims_queryset():
    """Claims with everything the sheet shows next to a name (attendee + their field values)."""
    return Claim.objects.select_related("attendee").prefetch_related(
        Prefetch("attendee__values", queryset=FieldValue.objects.select_related("field"))
    )


def sheet_categories(event):
    return Category.objects.filter(event=event).prefetch_related(
        "items", Prefetch("items__claims", queryset=claims_queryset())
    )


def load_category(event, pk, **filters):
    """One category of this event, prefetched like sheet_categories(). 404 if it isn't in the event."""
    return get_object_or_404(sheet_categories(event), pk=pk, **filters)


def load_item(event, pk):
    """One item of this event with its claims prefetched. 404 if it isn't in the event."""
    queryset = Item.objects.select_related("category").prefetch_related(
        Prefetch("claims", queryset=claims_queryset())
    )
    return get_object_or_404(queryset, pk=pk, category__event=event)


def sheet_context(request, event, me=_UNSET):
    """Context for templates/events/partials/sheet.html. Contract: keys event, categories, me, is_admin.

    `me` may be passed when the caller already looked up the current attendee.
    """
    return {
        "event": event,
        "categories": sheet_categories(event),
        "me": current_attendee(request, event) if me is _UNSET else me,
        "is_admin": request.is_admin,
    }
