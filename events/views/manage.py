"""Admin views: site settings, event setup, custom fields, inline sheet editing and responses."""

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from django_htmx.http import HttpResponseClientRedirect, retarget, reswap

from .. import services
from ..forms import (
    CategoryForm,
    CustomFieldForm,
    EventForm,
    ItemForm,
    NewEventFieldFormSet,
    NoteForm,
    SiteSettingsForm,
    build_profile_form,
)
from ..middleware import AdminKeyMiddleware
from ..models import Attendee, Category, Claim, CustomField, Event, FieldValue, Item, SiteSettings
from ..permissions import admin_required
from .sheet import sheet_context


@require_POST
def logout(request):
    request.session.pop(AdminKeyMiddleware.SESSION_KEY, None)
    request.session.pop(AdminKeyMiddleware.GUEST_VIEW_KEY, None)
    return redirect("landing")


def _back_to(request):
    """The page the button was on, if it's on this site; otherwise the home page."""
    target = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect("landing")


@admin_required
@require_POST
def guest_view_start(request):
    request.session[AdminKeyMiddleware.GUEST_VIEW_KEY] = True
    return _back_to(request)


@require_POST
def guest_view_exit(request):
    # In guest view request.is_admin is off, so check the underlying admin login instead.
    if not request.is_real_admin:
        raise Http404
    request.session.pop(AdminKeyMiddleware.GUEST_VIEW_KEY, None)
    return _back_to(request)


# ---------- helpers ----------


def _event(slug):
    return get_object_or_404(Event, slug=slug)


def _move(obj, siblings, direction):
    """Swap `obj` with its neighbour in `siblings`, renumbering positions so ties can't stick."""
    if direction not in ("up", "down"):
        raise Http404
    rows = list(siblings)
    i = next(n for n, row in enumerate(rows) if row.pk == obj.pk)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        with transaction.atomic():
            for n, row in enumerate(rows, start=1):
                if row.position != n:
                    row.position = n
                    row.save(update_fields=["position"])


def _sheet_response(request, event):
    if request.htmx:
        return render(request, "events/partials/sheet.html", sheet_context(request, event))
    return redirect(event.get_absolute_url())


def _sheet_form(request, event, form, *, action, form_id, heading, submit_label, status=200):
    """Render a category/item form: inline for htmx (retargeted onto itself on errors), else a page."""
    ctx = {
        "event": event,
        "form": form,
        "action": action,
        "form_id": form_id,
        "heading": heading,
        "submit_label": submit_label,
        "standalone": not request.htmx,
    }
    if not request.htmx:
        return render(request, "events/manage/form_page.html", ctx, status=status)
    response = render(request, "events/manage/partials/sheet_form.html", ctx)
    if request.method == "POST":
        response = reswap(retarget(response, f"#{form_id}"), "outerHTML")
    return response


# ---------- site ----------


@admin_required
@require_http_methods(["GET", "POST"])
def site_settings(request):
    # Bind to a fresh copy so rejected values never show up in the header or footer.
    form = SiteSettingsForm(request.POST or None, instance=SiteSettings.load())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Site settings saved.")
        return redirect("manage_site_settings")
    return render(request, "events/manage/site_settings.html", {"form": form})


# ---------- events ----------


@admin_required
@require_http_methods(["GET", "POST"])
def event_new(request):
    form = EventForm(request.POST or None)
    # The custom fields section is optional; a POST without it just adds no fields.
    fields_posted = "fields-TOTAL_FORMS" in request.POST
    field_formset = NewEventFieldFormSet(
        request.POST if fields_posted else None, queryset=CustomField.objects.none(), prefix="fields"
    )
    if request.method == "POST" and form.is_valid() and (not fields_posted or field_formset.is_valid()):
        with transaction.atomic():
            event = form.save(commit=False)
            if not event.slug:
                event.slug = services.unique_slug(event.title)
            event.save()
            for position, field in enumerate(field_formset.save(commit=False) if fields_posted else [], start=1):
                field.event = event
                field.position = position
                field.save()
        messages.success(request, "Event created. Add categories and items below.")
        return redirect(event.get_absolute_url())
    return render(request, "events/manage/event_new.html", {"form": form, "field_formset": field_formset})


def _settings_context(event, **extra):
    ctx = {
        "event": event,
        # answered: non-empty answers, so Make public can warn before showing private answers.
        "fields": event.fields.annotate(answered=Count("values", filter=~Q(values__value=""))),
        "field_form": CustomFieldForm(auto_id="newfield_%s"),
    }
    ctx.update(extra)
    return ctx


@admin_required
@require_http_methods(["GET", "POST"])
def event_settings(request, slug):
    event = _event(slug)
    # Bind to a copy so a rejected slug never leaks into links rendered from `event`.
    form = EventForm(request.POST or None, instance=Event.objects.get(pk=event.pk))
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        if not updated.slug:
            updated.slug = services.unique_slug(updated.title, exclude_pk=updated.pk)
        updated.save()
        messages.success(request, "Event details saved.")
        return redirect("manage_event_settings", slug=updated.slug)
    return render(request, "events/manage/settings.html", _settings_context(event, form=form))


@admin_required
@require_POST
def event_delete(request, slug):
    event = _event(slug)
    title = event.title
    event.delete()
    messages.success(request, f"Deleted “{title}”.")
    if request.htmx:
        return HttpResponseClientRedirect(reverse("landing"))
    return redirect("landing")


# ---------- custom fields ----------


def _fields_response(request, event, field_form=None, error=None, notice=None):
    if not request.htmx:
        if error:
            messages.error(request, error)
        if notice:
            messages.success(request, notice)
        return redirect("manage_event_settings", slug=event.slug)
    ctx = _settings_context(event, fields_error=error, fields_notice=notice)
    if field_form is not None:
        ctx["field_form"] = field_form
    return render(request, "events/manage/partials/fields.html", ctx)


@admin_required
@require_POST
def field_add(request, slug):
    event = _event(slug)
    form = CustomFieldForm(request.POST, auto_id="newfield_%s")
    if form.is_valid():
        field = form.save(commit=False)
        field.event = event
        field.position = services.next_position(event.fields.all())
        field.save()
        return _fields_response(request, event, notice=f"Field added: “{field.label}”")
    if not request.htmx:
        return render(
            request, "events/manage/settings.html",
            _settings_context(event, form=EventForm(instance=event), field_form=form),
        )
    return _fields_response(request, event, field_form=form)


@admin_required
@require_http_methods(["GET", "POST"])
def field_edit(request, slug, pk):
    event = _event(slug)
    field = get_object_or_404(CustomField, pk=pk, event=event)
    form = CustomFieldForm(request.POST or None, instance=field, auto_id=f"field{pk}_%s")
    if request.method == "POST" and form.is_valid():
        form.save()
        return _fields_response(request, event, notice="Field saved")
    ctx = {"event": event, "field": field, "form": form}
    if not request.htmx:
        return render(request, "events/manage/field_edit.html", ctx)
    response = render(request, "events/manage/partials/field_form.html", ctx)
    if request.method == "POST":
        response = reswap(retarget(response, f"#field-{pk}"), "outerHTML")
    return response


@admin_required
@require_POST
def field_delete(request, slug, pk):
    event = _event(slug)
    get_object_or_404(CustomField, pk=pk, event=event).delete()
    return _fields_response(request, event, notice="Field deleted")


@admin_required
@require_POST
def field_move(request, slug, pk, direction):
    event = _event(slug)
    field = get_object_or_404(CustomField, pk=pk, event=event)
    _move(field, event.fields.all(), direction)
    return _fields_response(request, event)


@admin_required
@require_POST
def field_toggle(request, slug, pk, attr):
    event = _event(slug)
    field = get_object_or_404(CustomField, pk=pk, event=event)
    name = {"required": "required", "public": "is_public"}.get(attr)
    if name is None:
        raise Http404
    if name == "is_public" and not field.is_public and request.POST.get("confirm") != "1":
        if field.values.exclude(value="").exists():
            return _fields_response(request, event, error=(
                f"“{field.label}” is still private. People answered it while it was private, "
                "so confirm before showing their answers to everyone."
            ))
    setattr(field, name, not getattr(field, name))
    field.save(update_fields=[name])
    return _fields_response(request, event)


# ---------- categories ----------


@admin_required
@require_http_methods(["GET", "POST"])
def category_add(request, slug):
    event = _event(slug)
    form = CategoryForm(request.POST or None, auto_id="newcategory_%s")
    if request.method == "POST" and form.is_valid():
        category = form.save(commit=False)
        category.event = event
        category.position = services.next_position(event.categories.all())
        category.save()
        return _sheet_response(request, event)
    return _sheet_form(
        request, event, form,
        action=reverse("manage_category_add", args=[event.slug]),
        form_id="category-form-new", heading="New category", submit_label="Add category",
    )


@admin_required
@require_http_methods(["GET", "POST"])
def category_edit(request, slug, pk):
    event = _event(slug)
    category = get_object_or_404(Category, pk=pk, event=event)
    form = CategoryForm(request.POST or None, instance=category, auto_id=f"adm-category{pk}_%s")
    if request.method == "POST" and form.is_valid():
        form.save()
        return _sheet_response(request, event)
    return _sheet_form(
        request, event, form,
        action=reverse("manage_category_edit", args=[event.slug, pk]),
        form_id=f"category-form-{pk}", heading=f"Edit {category.name}", submit_label="Save category",
    )


@admin_required
@require_POST
def category_delete(request, slug, pk):
    event = _event(slug)
    get_object_or_404(Category, pk=pk, event=event).delete()
    return _sheet_response(request, event)


@admin_required
@require_POST
def category_move(request, slug, pk, direction):
    event = _event(slug)
    category = get_object_or_404(Category, pk=pk, event=event)
    _move(category, event.categories.all(), direction)
    return _sheet_response(request, event)


@admin_required
@require_POST
def category_toggle_custom(request, slug, pk):
    event = _event(slug)
    category = get_object_or_404(Category, pk=pk, event=event)
    category.allow_custom_items = not category.allow_custom_items
    category.save(update_fields=["allow_custom_items"])
    return _sheet_response(request, event)


# ---------- items ----------


@admin_required
@require_http_methods(["GET", "POST"])
def item_add(request, slug, category_pk):
    event = _event(slug)
    category = get_object_or_404(Category, pk=category_pk, event=event)
    form = ItemForm(request.POST or None, auto_id=f"newitem{category_pk}_%s")
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.category = category
        item.position = services.next_position(category.items.all())
        item.save()
        return _sheet_response(request, event)
    return _sheet_form(
        request, event, form,
        action=reverse("manage_item_add", args=[event.slug, category.pk]),
        form_id=f"item-form-new-{category.pk}", heading=f"New suggested item in {category.name}",
        submit_label="Add suggested item",
    )


@admin_required
@require_http_methods(["GET", "POST"])
def item_edit(request, slug, pk):
    event = _event(slug)
    item = get_object_or_404(Item, pk=pk, category__event=event)
    form = ItemForm(request.POST or None, instance=item, auto_id=f"adm-item{pk}_%s")
    if request.method == "POST" and form.is_valid():
        form.save()
        return _sheet_response(request, event)
    return _sheet_form(
        request, event, form,
        action=reverse("manage_item_edit", args=[event.slug, pk]),
        form_id=f"item-form-{pk}", heading=f"Edit {item.name}", submit_label="Save item",
    )


@admin_required
@require_POST
def item_delete(request, slug, pk):
    event = _event(slug)
    get_object_or_404(Item, pk=pk, category__event=event).delete()
    return _sheet_response(request, event)


@admin_required
@require_POST
def item_move(request, slug, pk, direction):
    event = _event(slug)
    item = get_object_or_404(Item, pk=pk, category__event=event)
    _move(item, item.category.items.filter(is_custom=item.is_custom), direction)
    return _sheet_response(request, event)


# ---------- responses ----------


def _responses_context(event):
    fields = list(event.fields.all())
    attendees = (
        event.attendees.order_by("created_at", "id")
        .prefetch_related(
            Prefetch("values", queryset=FieldValue.objects.select_related("field")),
            Prefetch("claims", queryset=Claim.objects.select_related("item", "item__category")),
        )
    )
    rows = []
    for attendee in attendees:
        by_field = {fv.field_id: fv for fv in attendee.values.all()}
        rows.append({"attendee": attendee, "values": [by_field.get(f.pk) for f in fields]})
    return {"event": event, "fields": fields, "rows": rows}


def _responses_response(request, event):
    if request.htmx:
        return render(request, "events/manage/partials/responses_table.html", _responses_context(event))
    return redirect("manage_event_responses", slug=event.slug)


@admin_required
def event_responses(request, slug):
    event = _event(slug)
    return render(request, "events/manage/responses.html", _responses_context(event))


@admin_required
@require_http_methods(["GET", "POST"])
def attendee_edit(request, slug, pk):
    event = _event(slug)
    attendee = get_object_or_404(Attendee, pk=pk, event=event)
    form = build_profile_form(event, request.POST or None, attendee=attendee)
    if request.method == "POST" and form.is_valid():
        services.save_profile(
            event, attendee.token, form.cleaned_data["name"], form.field_values(), attendee=attendee
        )
        messages.success(request, f"Saved {attendee.name}’s details.")
        return redirect("manage_event_responses", slug=event.slug)
    return render(
        request, "events/manage/attendee_edit.html", {"event": event, "attendee": attendee, "form": form}
    )


@admin_required
@require_POST
def attendee_delete(request, slug, pk):
    event = _event(slug)
    attendee = get_object_or_404(Attendee, pk=pk, event=event)
    with transaction.atomic():
        # Go through remove_claim so attendee-added items vanish with their last claim.
        for claim in list(attendee.claims.select_related("item")):
            services.remove_claim(claim)
        attendee.delete()
    return _responses_response(request, event)


@admin_required
@require_POST
def claim_delete(request, slug, pk):
    event = _event(slug)
    services.remove_claim(get_object_or_404(Claim, pk=pk, item__category__event=event))
    return _responses_response(request, event)


@admin_required
@require_http_methods(["GET", "POST"])
def claim_note(request, slug, pk):
    event = _event(slug)
    claim = get_object_or_404(Claim.objects.select_related("item", "attendee"), pk=pk, item__category__event=event)
    form = NoteForm(request.POST or None, initial={"note": claim.note}, auto_id=f"adm-claim{pk}_%s")
    if request.method == "POST" and form.is_valid():
        claim.note = form.cleaned_data["note"].strip()
        claim.save(update_fields=["note"])
        return _responses_response(request, event)
    ctx = {"event": event, "claim": claim, "form": form}
    if not request.htmx:
        return render(request, "events/manage/claim_note.html", ctx)
    response = render(request, "events/manage/partials/claim_note_form.html", ctx)
    if request.method == "POST":
        response = reswap(retarget(response, f"#claim-{pk}"), "outerHTML")
    return response
