"""Transactional business logic shared by public and admin views."""

import secrets
import time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify

from .models import RESERVED_SLUGS, Attendee, Category, Claim, Event, FieldValue, Item


class ItemFull(Exception):
    """Raised when every slot of an item is already claimed."""


class CustomItemsNotAllowed(Exception):
    pass


class CustomItemsFull(Exception):
    """Raised when a category already has as many attendee-added items as its limit allows."""


class TooManyClaims(Exception):
    """Raised when an attendee already holds settings.MAX_CLAIMS_PER_ITEM claims on an unlimited item."""


class TooManyCustomItems(Exception):
    """Raised when an attendee already added settings.MAX_CUSTOM_ITEMS_PER_ATTENDEE items to a category."""


# Lowercase letters and digits minus the easily confused i, l, o, 0 and 1. Keep in sync with static/js/app.js.
SLUG_SUFFIX_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SLUG_SUFFIX_LENGTH = 4


def slug_suffix():
    return "".join(secrets.choice(SLUG_SUFFIX_ALPHABET) for _ in range(SLUG_SUFFIX_LENGTH))


def unique_slug(title, exclude_pk=None, random_suffix=True):
    """A free slug for `title`. With random_suffix (the default) it gets a hard-to-guess ending, like picnic-k3f9."""
    base = slugify(title)[:70].strip("-") or "event"
    if base in RESERVED_SLUGS:
        base = f"{base}-event"
    existing = Event.objects.exclude(pk=exclude_pk).filter(slug__startswith=base)
    taken = set(existing.values_list("slug", flat=True))
    if random_suffix:
        slug = f"{base}-{slug_suffix()}"
        while slug in taken:
            slug = f"{base}-{slug_suffix()}"
        return slug
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def next_position(queryset):
    return (queryset.aggregate(m=Max("position"))["m"] or 0) + 1


def claim_slot(item, attendee, note=""):
    # transaction_mode=IMMEDIATE (settings) serializes writers, so count-then-insert is safe.
    with transaction.atomic():
        item = Item.objects.filter(pk=item.pk).first()
        if item is None:  # an attendee-added item vanished with its last claim
            raise ItemFull(None)
        if item.slots is not None and item.claims.count() >= item.slots:
            raise ItemFull(item)
        # Limited items are capped by their slots; unlimited ones get a per-person cap against spam.
        if item.slots is None and item.claims.filter(attendee=attendee).count() >= settings.MAX_CLAIMS_PER_ITEM:
            raise TooManyClaims(item)
        return Claim.objects.create(item=item, attendee=attendee, note=note.strip())


def add_custom_item(category, attendee, name, note=""):
    # transaction_mode=IMMEDIATE (settings) serializes writers, so count-then-insert is safe.
    with transaction.atomic():
        category = Category.objects.get(pk=category.pk)
        if not category.allow_custom_items:
            raise CustomItemsNotAllowed(category)
        limit = category.custom_item_limit
        if limit is not None and category.items.filter(is_custom=True).count() >= limit:
            raise CustomItemsFull(category)
        mine = category.items.filter(is_custom=True, created_by=attendee).count()
        if mine >= settings.MAX_CUSTOM_ITEMS_PER_ATTENDEE:
            raise TooManyCustomItems(category)
        item = Item.objects.create(
            category=category,
            name=name.strip(),
            slots=1,  # one person per attendee-added item
            is_custom=True,
            created_by=attendee,
            position=next_position(category.items.all()),
        )
        Claim.objects.create(item=item, attendee=attendee, note=note.strip())
    return item


def remove_claim(claim):
    """Delete a claim; an attendee-added item disappears with its last claim. Returns the item or None."""
    with transaction.atomic():
        item = claim.item
        claim.delete()
        if item.is_custom and not item.claims.exists():
            item.delete()
            return None
    return item


def client_ip(request):
    """REMOTE_ADDR, or the first X-Forwarded-For address when a trusted proxy sits in front."""
    if settings.BEHIND_PROXY:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.META.get("REMOTE_ADDR", "")


def allow_new_attendee(ip):
    """Count a new attendee profile from `ip`; False once it passes settings.NEW_ATTENDEES_PER_HOUR."""
    key = f"new-attendees:{ip}:{int(time.time() // 3600)}"
    cache.add(key, 0, timeout=60 * 60)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=60 * 60)
        count = 1
    return count <= settings.NEW_ATTENDEES_PER_HOUR


def save_profile(event, token, name, values, attendee=None):
    """Create or update an attendee profile. `values` maps CustomField -> string value."""
    with transaction.atomic():
        if attendee is None:
            attendee, _ = Attendee.objects.get_or_create(
                event=event, token=token, defaults={"name": name}
            )
        attendee.name = name
        attendee.save()
        for field, value in values.items():
            FieldValue.objects.update_or_create(
                attendee=attendee, field=field, defaults={"value": value}
            )
    return attendee
