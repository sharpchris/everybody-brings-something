"""Forms for the admin pages and the attendee signup flow."""

import re
import zoneinfo

from django import forms

from .models import Category, CustomField, Event, Item, SiteSettings
from .services import unique_slug

# Light check: digits plus common separators, and a plausible number of digits.
PHONE_CHARS_RE = re.compile(r"^\+?[0-9()\-.\s]+$")
PHONE_MIN_DIGITS, PHONE_MAX_DIGITS = 7, 15


# Listed first in the time zone menu; everything else follows alphabetically.
COMMON_TIME_ZONES = [
    ("America/New_York", "Eastern (New York)"),
    ("America/Chicago", "Central (Chicago)"),
    ("America/Denver", "Mountain (Denver)"),
    ("America/Phoenix", "Arizona (Phoenix)"),
    ("America/Los_Angeles", "Pacific (Los Angeles)"),
    ("America/Anchorage", "Alaska (Anchorage)"),
    ("Pacific/Honolulu", "Hawaii (Honolulu)"),
]


def time_zone_choices():
    common = {name for name, _ in COMMON_TIME_ZONES}
    others = sorted(tz for tz in zoneinfo.available_timezones() if tz not in common)
    return [("Common", COMMON_TIME_ZONES), ("All time zones", [(tz, tz.replace("_", " ")) for tz in others])]


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["organization", "time_zone", "home_message", "contact_email"]
        labels = {"home_message": "Home page message"}
        help_texts = {
            "time_zone": "Event dates and times are shown in this time zone.",
            "contact_email": "Shown at the bottom of every page so people can reach you.",
        }
        widgets = {"home_message": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A select instead of free text; the model validator still rejects anything unknown.
        self.fields["time_zone"].widget = forms.Select(choices=time_zone_choices())


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)


class EventForm(forms.ModelForm):
    """Event details. On create, the share link follows the title until it's edited by hand."""

    # Set by static/js/app.js while the slug is still being filled in from the title.
    slug_auto = forms.BooleanField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Event
        fields = ["title", "slug", "starts_at", "ends_at", "location", "description"]
        widgets = {
            "title": forms.TextInput(attrs={"data-slug-source": ""}),
            "slug": forms.TextInput(attrs={"data-slug-target": ""}),
            "starts_at": DateTimeLocalInput(),
            "ends_at": DateTimeLocalInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {"starts_at": "Starts", "ends_at": "Ends", "slug": "Share link"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        if self.instance.pk:
            # Changing the title of an existing event must not silently change its link.
            self.fields["slug"].widget.attrs["data-slug-locked"] = ""

    def clean_slug(self):
        return (self.cleaned_data.get("slug") or "").strip().lower()

    def clean(self):
        data = super().clean()
        slug = data.get("slug")
        if slug and data.get("slug_auto"):
            # An auto-filled link that's taken gets a -2 suffix instead of an error.
            data["slug"] = unique_slug(slug, exclude_pk=self.instance.pk, random_suffix=False)
        return data


class CategoryForm(forms.ModelForm):
    unlimited_custom = forms.BooleanField(required=False, label="No limit")

    class Meta:
        model = Category
        fields = ["name", "description", "allow_custom_items", "custom_item_limit"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}
        labels = {"allow_custom_items": "Attendees can add items", "custom_item_limit": "Items attendees can add"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["custom_item_limit"].widget.attrs["min"] = 1
        if self.instance.pk:
            self.initial["unlimited_custom"] = self.instance.custom_item_limit is None

    def clean(self):
        data = super().clean()
        if data.get("unlimited_custom"):
            data["custom_item_limit"] = None
        elif data.get("allow_custom_items") and not data.get("custom_item_limit"):
            self.add_error("custom_item_limit", "Enter how many items attendees can add, or tick No limit.")
        elif not data.get("allow_custom_items") and not data.get("custom_item_limit"):
            # Not used while attendees can't add; keep the previous (or default) cap for later.
            data["custom_item_limit"] = self.instance.custom_item_limit if self.instance.pk else Category.DEFAULT_CUSTOM_ITEM_LIMIT
        # Set it on the instance too: ModelForm skips fields missing from the POST data.
        self.instance.custom_item_limit = data.get("custom_item_limit")
        return data


class ItemForm(forms.ModelForm):
    unlimited = forms.BooleanField(required=False, label="Unlimited signups")

    class Meta:
        model = Item
        fields = ["name", "description", "slots"]
        labels = {"slots": "Signups allowed"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slots"].widget.attrs["min"] = 1
        if self.instance.pk:
            self.initial["unlimited"] = self.instance.slots is None
        elif "slots" not in self.initial:
            self.initial["slots"] = 1

    def clean(self):
        data = super().clean()
        if data.get("unlimited"):
            data["slots"] = None
        elif not data.get("slots"):
            self.add_error("slots", "Enter how many signups are allowed, or tick Unlimited.")
        return data


class CustomFieldForm(forms.ModelForm):
    class Meta:
        model = CustomField
        fields = ["label", "field_type", "required", "is_public", "help_text"]
        labels = {"is_public": "Visible to other attendees"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.was_public = self.instance.is_public
        values = self.instance.values.all() if self.instance.pk else None
        if values is not None and values.exists():
            # Stored answers only make sense for the type they were given as.
            self.fields["field_type"].disabled = True
            self.fields["field_type"].help_text = "Can't change the type after people have answered. Add a new field instead."
        self.private_answers = values.exclude(value="").count() if values is not None and not self.was_public else 0
        if self.private_answers:
            n = self.private_answers
            self.fields["confirm_public"] = forms.BooleanField(
                required=False,
                label="I understand existing answers will be shown",
                help_text=f"{n} {'person' if n == 1 else 'people'} answered while this field was private. "
                "Tick this if you make it visible.",
            )
            self.order_fields(["label", "field_type", "required", "is_public", "confirm_public"])

    def clean(self):
        data = super().clean()
        if self.private_answers and data.get("is_public") and not data.get("confirm_public"):
            self.add_error("confirm_public", "Confirm that earlier private answers will become visible to everyone.")
        return data


class NewEventFieldForm(forms.ModelForm):
    """One custom field row on the new-event page. Untouched rows are skipped."""

    class Meta:
        model = CustomField
        fields = ["label", "field_type", "required", "is_public"]
        labels = {"label": "Question", "is_public": "Visible to other attendees"}
        widgets = {"label": forms.TextInput(attrs={"placeholder": "e.g. Child, class, or group"})}


NewEventFieldFormSet = forms.modelformset_factory(CustomField, form=NewEventFieldForm, extra=2)


class NoteForm(forms.Form):
    note = forms.CharField(max_length=200, required=False, label="Note (optional)")


class CustomItemForm(forms.Form):
    name = forms.CharField(max_length=160, label="What are you bringing?")
    note = forms.CharField(max_length=200, required=False, label="Note (optional)")


class PhoneField(forms.CharField):
    widget = forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel"})

    def clean(self, value):
        value = super().clean(value).strip()
        if value:
            digits = sum(ch.isdigit() for ch in value)
            if not PHONE_CHARS_RE.match(value) or not PHONE_MIN_DIGITS <= digits <= PHONE_MAX_DIGITS:
                raise forms.ValidationError("Enter a phone number, like 555-123-4567.")
        return value


def _form_field_for(field: CustomField):
    common = {"label": field.label, "required": field.required, "help_text": field.help_text}
    match field.field_type:
        case CustomField.EMAIL:
            return forms.EmailField(
                error_messages={"invalid": "Enter an email address, like name@example.com."},
                widget=forms.EmailInput(attrs={"autocomplete": "email"}),
                **common,
            )
        case CustomField.CHECKBOX if field.required:
            # A required single checkbox would force a tick, so required yes/no questions get Yes and No.
            return forms.TypedChoiceField(
                choices=[(True, "Yes"), (False, "No")],
                coerce=lambda value: value in (True, "True"),
                widget=forms.RadioSelect,
                **common,
            )
        case CustomField.CHECKBOX:
            return forms.BooleanField(**common)
        case CustomField.PHONE:
            return PhoneField(max_length=30, **common)
        case _:
            return forms.CharField(max_length=300, **common)


class ProfileForm(forms.Form):
    """Name plus the event's custom fields. Use build_profile_form() to construct."""

    name = forms.CharField(
        max_length=120, label="Your name", widget=forms.TextInput(attrs={"autocomplete": "name"})
    )

    def __init__(self, *args, event, attendee=None, **kwargs):
        self.event = event
        self.custom_fields = list(event.fields.all())
        if attendee is not None and "initial" not in kwargs:
            initial = {"name": attendee.name}
            for v in attendee.values.all():
                initial[v.field.form_key] = v.value == "1" if v.field.field_type == CustomField.CHECKBOX else v.value
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        for cf in self.custom_fields:
            self.fields[cf.form_key] = _form_field_for(cf)

    def field_values(self):
        """Map CustomField -> stored string value, for services.save_profile()."""
        out = {}
        for cf in self.custom_fields:
            raw = self.cleaned_data.get(cf.form_key)
            if cf.field_type == CustomField.CHECKBOX:
                out[cf] = "1" if raw else "0"
            else:
                out[cf] = "" if raw is None else str(raw)
        return out


def build_profile_form(event, data=None, attendee=None):
    return ProfileForm(data, event=event, attendee=attendee)
