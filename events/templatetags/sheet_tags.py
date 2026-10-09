"""Template helpers for the signup sheet: slot rows, event dates and shared defaults."""

from django import template
from django.utils import dateformat, timezone

from ..models import Category

register = template.Library()

# Big items still show a few blank lines; the rest is summarised as "N more open".
MAX_OPEN_LINES = 3


def _label_value(label, value):
    """"Guest: Bea", but "Bringing a guest? Dev" rather than "Bringing a guest?: Dev"."""
    sep = " " if label.rstrip()[-1:] in "?:!." else ": "
    return f"{label.rstrip()}{sep}{value}"


@register.simple_tag
def slot_state(item, me=None):
    """Everything item.html needs about an item's slots, from the prefetched claims (no queries).

    Signer extras come only from Attendee.public_values(): private answers never reach the sheet.
    """
    claims = list(item.claims.all())
    count = len(claims)
    my_pk = getattr(me, "pk", None)
    rows = []
    for claim in claims:
        extras = [_label_value(v.field.label, v.display) for v in claim.attendee.public_values()]
        mine = my_pk is not None and claim.attendee_id == my_pk
        rows.append({"claim": claim, "mine": mine, "extras": extras})

    if item.slots is None:
        remaining, open_lines = None, 1
    else:
        remaining = max(item.slots - count, 0)
        open_lines = min(remaining, MAX_OPEN_LINES)
    return {
        "rows": rows,
        "count": count,
        "mine_count": sum(1 for r in rows if r["mine"]),
        "full": item.slots is not None and count >= item.slots,
        "over": item.slots is not None and count > item.slots,
        "open_lines": range(open_lines),
        "more_open": (remaining - open_lines) if remaining is not None else 0,
    }


@register.simple_tag
def move_bounds(item, category):
    """Whether `item` is first/last among the items it can swap with (custom items move among themselves)."""
    siblings = [i.pk for i in category.items.all() if i.is_custom == item.is_custom]
    return {"first": siblings[:1] == [item.pk], "last": siblings[-1:] == [item.pk]}


@register.simple_tag(takes_context=True)
def category_bounds(context, category):
    """Whether `category` is first/last in its event, in full-sheet and single-category renders alike."""
    categories = context.get("categories")
    if categories is not None:  # the full sheet's (already evaluated) queryset
        pks = [c.pk for c in categories]
    else:
        pks = list(Category.objects.filter(event_id=category.event_id).values_list("pk", flat=True))
    return {"first": pks[:1] == [category.pk], "last": pks[-1:] == [category.pk]}


def _day(dt, now):
    return dateformat.format(dt, "l, F j" if dt.year == now.year else "l, F j, Y")


def _time(dt):
    return dateformat.format(dt, "g:i A").replace(":00", "")


@register.filter
def event_when(event):
    """'Saturday, June 14 · 5–8 PM' style range in the site's time zone."""
    if not event.starts_at:
        return ""
    now = timezone.localtime()
    start = timezone.localtime(event.starts_at)
    if not event.ends_at or event.ends_at == event.starts_at:
        return f"{_day(start, now)} · {_time(start)}"
    end = timezone.localtime(event.ends_at)
    if start.date() == end.date():
        start_t, end_t = _time(start), _time(end)
        if start_t[-2:] == end_t[-2:]:  # same AM/PM: "5–8 PM"
            start_t = start_t[:-3]
        return f"{_day(start, now)} · {start_t}–{end_t}"
    return f"{_day(start, now)}, {_time(start)} – {_day(end, now)}, {_time(end)}"


@register.simple_tag
def default_custom_item_limit():
    """How many items attendees can add to a new category (Category.DEFAULT_CUSTOM_ITEM_LIMIT)."""
    return Category.DEFAULT_CUSTOM_ITEM_LIMIT
