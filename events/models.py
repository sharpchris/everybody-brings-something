"""Data model: events, their categories and items, custom fields, attendees and claims,
plus the single-row site settings."""

import uuid
import zoneinfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

# Slugs that would collide with top-level routes.
RESERVED_SLUGS = {"manage", "static", "health", "admin", "favicon.ico", "robots.txt", "api"}


SITE_NAME = "Everybody Brings Something"


def validate_not_reserved(value):
    if value.lower() in RESERVED_SLUGS:
        raise ValidationError(f"“{value}” is reserved; please choose another slug.")


class Event(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True, validators=[validate_not_reserved])
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at", "-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("event_detail", args=[self.slug])

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValidationError({"ends_at": "End must be after the start."})


class Category(models.Model):
    # How many items attendees can add to a new category unless the organizer changes it.
    DEFAULT_CUSTOM_ITEM_LIMIT = 10

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    allow_custom_items = models.BooleanField(
        default=True, help_text="Let attendees add their own items to this category."
    )
    # How many items attendees can add here (one person each). None means no limit.
    custom_item_limit = models.PositiveIntegerField(
        null=True, blank=True, default=DEFAULT_CUSTOM_ITEM_LIMIT, validators=[MinValueValidator(1)]
    )

    class Meta:
        ordering = ["position", "id"]
        verbose_name_plural = "categories"

    @property
    def has_suggested_items(self):
        """Whether the organizer listed any items here; uses prefetched items when available."""
        return any(not item.is_custom for item in self.items.all())

    @property
    def custom_count(self):
        """Attendee-added items so far; uses prefetched items when available."""
        return sum(1 for item in self.items.all() if item.is_custom)

    @property
    def custom_spots_left(self):
        if self.custom_item_limit is None:
            return None
        return max(0, self.custom_item_limit - self.custom_count)

    @property
    def custom_full(self):
        return self.custom_spots_left == 0

    def __str__(self):
        return f"{self.event} / {self.name}"


class Item(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=300, blank=True)
    # None means unlimited signups.
    slots = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    is_custom = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        "Attendee", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_items"
    )

    class Meta:
        ordering = ["is_custom", "position", "id"]

    def __str__(self):
        return self.name

    @property
    def is_unlimited(self):
        return self.slots is None


class CustomField(models.Model):
    TEXT = "text"
    PHONE = "phone"
    EMAIL = "email"
    CHECKBOX = "checkbox"
    TYPE_CHOICES = [
        (TEXT, "Text"),
        (PHONE, "Phone number"),
        (EMAIL, "Email"),
        (CHECKBOX, "Yes/No (Checkbox)"),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TEXT)
    required = models.BooleanField(default=False)
    is_public = models.BooleanField(
        default=False, help_text="Show this answer to other attendees next to the person's name."
    )
    help_text = models.CharField(max_length=200, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.label

    @property
    def form_key(self):
        return f"field_{self.pk}"


class Attendee(models.Model):
    """An attendee's profile for one event, tied to their browser cookie token."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attendees")
    token = models.UUIDField(default=uuid.uuid4, db_index=True)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "token"], name="unique_attendee_per_event")
        ]

    def __str__(self):
        return self.name

    def public_values(self):
        """Field values safe to show to other attendees. Templates must use this, never .values."""
        return [v for v in self.values.all() if v.field.is_public and v.value]


class FieldValue(models.Model):
    attendee = models.ForeignKey(Attendee, on_delete=models.CASCADE, related_name="values")
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="values")
    value = models.TextField(blank=True)

    class Meta:
        ordering = ["field__position", "field__id"]
        constraints = [
            models.UniqueConstraint(fields=["attendee", "field"], name="unique_value_per_field")
        ]

    def __str__(self):
        return f"{self.field.label}: {self.value}"

    @property
    def display(self):
        if self.field.field_type == CustomField.CHECKBOX:
            return "Yes" if self.value == "1" else "No"
        return self.value


class Claim(models.Model):
    """One attendee taking one slot of an item."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="claims")
    attendee = models.ForeignKey(Attendee, on_delete=models.CASCADE, related_name="claims")
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.attendee} → {self.item}"


def validate_time_zone(value):
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"“{value}” isn't a known time zone.")


def default_time_zone():
    return settings.TIME_ZONE


class SiteSettings(models.Model):
    """Site-wide settings an admin edits in the app. There is only ever one row."""

    organization = models.CharField(
        max_length=80, blank=True, help_text="Shown after the site name, e.g. “Riverside PTA”."
    )
    time_zone = models.CharField(max_length=64, default=default_time_zone, validators=[validate_time_zone])
    home_message = models.TextField(
        blank=True, help_text="Shown on the home page to people who don't have an event link."
    )
    contact_email = models.EmailField(blank=True, help_text="Shown at the bottom of every page.")

    class Meta:
        verbose_name_plural = "site settings"

    def __str__(self):
        return self.title

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def title(self):
        return f"{SITE_NAME} – {self.organization}" if self.organization else SITE_NAME
