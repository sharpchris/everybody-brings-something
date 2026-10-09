"""Attendee-facing pages: the landing page, the event sheet, signing up, notes and profiles.

Every htmx interaction on an item targets its row (`#item-<pk>`, outerHTML) and every category-level
interaction targets the category (`#category-<pk>`). Without htmx, mutations redirect back to the event
page, and form-showing GETs render the whole page with that form open.
"""

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_http_methods, require_safe, require_POST
from django_htmx.http import reswap, retarget

from ..forms import CustomItemForm, NoteForm, build_profile_form
from ..models import Claim, Event, FieldValue
from ..permissions import current_attendee, ensure_can_edit
from ..services import (
    CustomItemsFull,
    CustomItemsNotAllowed,
    ItemFull,
    TooManyClaims,
    TooManyCustomItems,
    add_custom_item,
    allow_new_attendee,
    claim_slot,
    client_ip,
    remove_claim,
    save_profile,
)
from .sheet import load_category, load_item, sheet_context

# ---------- helpers ----------


def _profile_form(event, data=None, attendee=None, prefix_id="me"):
    """build_profile_form() plus friendlier errors, unique ids, and a public/private hint per field."""
    form = build_profile_form(event, data, attendee=attendee)
    form.auto_id = f"{prefix_id}_%s"
    form.fields["name"].error_messages["required"] = "Enter your name so people know who's bringing what."
    for cf in form.custom_fields:
        field = form.fields[cf.form_key]
        field.ebs_visibility = "public" if cf.is_public else "private"
        field.error_messages["required"] = f"{cf.label} is required for this event."
    return form


def _rate_limited(request, form):
    """True (with an error on `form`) when this network has made too many new profiles lately."""
    if allow_new_attendee(client_ip(request)):
        return False
    form.add_error(None, "Too many new signups from your network. Try again later.")
    return True


def _full_message(item):
    if item.slots == 1:
        return f"Someone already signed up for {item.name}. Pick another item."
    return f"All {item.slots} slots for {item.name} are taken. Pick another item."


def _is_full(item):
    return item.slots is not None and len(item.claims.all()) >= item.slots


def _panel_context(event, me, **extra):
    my_values = list(FieldValue.objects.filter(attendee=me).select_related("field")) if me else []
    return {"event": event, "me": me, "my_values": my_values, **extra}


def _render_panel(request, event, me, **extra):
    return render_to_string("events/partials/my_profile.html", _panel_context(event, me, **extra), request)


def _render_page(request, event, me, **extra):
    ctx = sheet_context(request, event, me=me)
    ctx.update(_panel_context(event, me))
    ctx.update(extra)
    return render(request, "events/event_detail.html", ctx)


def _back_to(event, anchor=""):
    return redirect(event.get_absolute_url() + (f"#{anchor}" if anchor else ""))


def _show_item(request, event, item_pk, me, *, panel=False, **state):
    """Re-render one item row (htmx), or the whole page with the same state (no JS).

    `state` may hold item_mode ("profile" / "note"), signup_form, note_form, editing_claim_id,
    error and just_claimed_id. `panel=True` appends the "Your info" panel as an OOB swap.
    """
    item = load_item(event, item_pk)
    state["active_item_id"] = item.pk
    if not request.htmx:
        return _render_page(request, event, me, **state)
    ctx = {"event": event, "category": item.category, "item": item, "me": me, "is_admin": request.is_admin, **state}
    html = render_to_string("events/partials/item.html", ctx, request)
    if panel:
        html += _render_panel(request, event, me, oob=True)
    return HttpResponse(html)


def _show_category(request, event, category_pk, me, *, panel=False, **state):
    """Re-render one category (htmx), or the whole page with the same state (no JS).

    `state` may hold category_mode ("add"), custom_form, signup_form and just_claimed_id.
    """
    category = load_category(event, category_pk)
    state["active_category_id"] = category.pk
    if not request.htmx:
        return _render_page(request, event, me, **state)
    ctx = {"event": event, "category": category, "me": me, "is_admin": request.is_admin, **state}
    html = render_to_string("events/partials/category.html", ctx, request)
    if panel:
        html += _render_panel(request, event, me, oob=True)
    return HttpResponse(html)


def _event_claim(event, claim_id):
    return get_object_or_404(
        Claim.objects.select_related("attendee", "item"), pk=claim_id, item__category__event=event
    )


# ---------- pages ----------


@require_safe
def landing(request):
    events = Event.objects.all() if request.is_admin else Event.objects.none()
    return render(request, "events/landing.html", {"events": events})


@require_safe
def event_detail(request, slug):
    event = get_object_or_404(Event, slug=slug)
    return _render_page(request, event, current_attendee(request, event))


@require_GET
def item_row(request, slug, item_id):
    """The plain item row; used by Cancel links on inline forms."""
    event = get_object_or_404(Event, slug=slug)
    item = load_item(event, item_id)
    if not request.htmx:
        return _back_to(event, f"item-{item.pk}")
    return _show_item(request, event, item.pk, current_attendee(request, event))


@require_GET
def category_row(request, slug, category_id):
    """The plain category; used by the Cancel link on the "Add your own" form."""
    event = get_object_or_404(Event, slug=slug)
    category = load_category(event, category_id)
    if not request.htmx:
        return _back_to(event, f"category-{category.pk}")
    return _show_category(request, event, category.pk, current_attendee(request, event))


# ---------- signing up ----------


@require_POST
def claim(request, slug, item_id):
    """Take one slot. First-time attendees get the profile form in the row; it posts back here."""
    event = get_object_or_404(Event, slug=slug)
    item = load_item(event, item_id)
    me = current_attendee(request, event)
    submitted_profile = "profile" in request.POST
    note_form = NoteForm(
        request.POST if submitted_profile or "note" in request.POST else None, auto_id=f"item{item.pk}_%s"
    )
    created_profile = False

    if me is None:
        if _is_full(item):
            return _show_item(request, event, item.pk, me, error=_full_message(item))
        signup_form = _profile_form(event, request.POST if submitted_profile else None, prefix_id=f"item{item.pk}")
        if (
            not submitted_profile
            or not (signup_form.is_valid() & note_form.is_valid())
            or _rate_limited(request, signup_form)
        ):
            return _show_item(
                request, event, item.pk, me, item_mode="profile", signup_form=signup_form, note_form=note_form
            )
        me = save_profile(event, request.attendee_token, signup_form.cleaned_data["name"], signup_form.field_values())
        created_profile = True
    elif note_form.is_bound and not note_form.is_valid():
        return _show_item(request, event, item.pk, me, error="Notes can be up to 200 characters.")

    note = note_form.cleaned_data.get("note", "") if note_form.is_bound else ""
    try:
        new_claim = claim_slot(item, me, note)
    except ItemFull:
        return _show_item(request, event, item.pk, me, panel=created_profile, error=_full_message(item))
    except TooManyClaims:
        error = f"You've already signed up for {item.name} {settings.MAX_CLAIMS_PER_ITEM} times."
        return _show_item(request, event, item.pk, me, panel=created_profile, error=error)
    if not request.htmx:
        return _back_to(event, f"item-{item.pk}")
    return _show_item(request, event, item.pk, me, panel=created_profile, just_claimed_id=new_claim.pk)


@require_http_methods(["GET", "POST"])
def claim_note(request, slug, claim_id):
    event = get_object_or_404(Event, slug=slug)
    the_claim = _event_claim(event, claim_id)
    ensure_can_edit(request, the_claim.attendee)
    me = current_attendee(request, event)

    if request.method == "POST":
        form = NoteForm(request.POST)
        if form.is_valid():
            the_claim.note = form.cleaned_data["note"].strip()
            the_claim.save(update_fields=["note"])
            if not request.htmx:
                return _back_to(event, f"item-{the_claim.item_id}")
            return _show_item(request, event, the_claim.item_id, me)
    else:
        form = NoteForm(initial={"note": the_claim.note})
    form.auto_id = f"claim{the_claim.pk}_%s"
    return _show_item(
        request, event, the_claim.item_id, me, item_mode="note", editing_claim_id=the_claim.pk, note_form=form
    )


@require_POST
def claim_delete(request, slug, claim_id):
    event = get_object_or_404(Event, slug=slug)
    the_claim = _event_claim(event, claim_id)
    ensure_can_edit(request, the_claim.attendee)
    category_id = the_claim.item.category_id
    item = remove_claim(the_claim)
    if not request.htmx:
        return _back_to(event, f"item-{item.pk}" if item else f"category-{category_id}")
    me = current_attendee(request, event)
    if item is None:
        # The attendee-added item went away with its last claim; redraw the whole category instead.
        response = _show_category(request, event, category_id, me)
        return reswap(retarget(response, f"#category-{category_id}"), "outerHTML")
    return _show_item(request, event, item.pk, me)


@require_http_methods(["GET", "POST"])
def custom_item(request, slug, category_id):
    """"Add your own": name + note, plus the profile fields if this attendee hasn't given them yet."""
    event = get_object_or_404(Event, slug=slug)
    category = load_category(event, category_id, allow_custom_items=True)
    me = current_attendee(request, event)
    prefix = f"category{category.pk}"

    if request.method == "GET":
        custom_form = CustomItemForm(prefix="item", auto_id=f"{prefix}_%s")
        signup_form = None if me else _profile_form(event, prefix_id=prefix)
        return _show_category(
            request, event, category.pk, me, category_mode="add", custom_form=custom_form, signup_form=signup_form
        )

    # Prefixed: both this form and the profile form have a "name" field.
    custom_form = CustomItemForm(request.POST, prefix="item", auto_id=f"{prefix}_%s")
    signup_form = None if me else _profile_form(event, request.POST, prefix_id=prefix)
    valid = custom_form.is_valid()
    if signup_form is not None:
        valid = signup_form.is_valid() and valid and not _rate_limited(request, signup_form)
    if not valid:
        return _show_category(
            request, event, category.pk, me, category_mode="add", custom_form=custom_form, signup_form=signup_form
        )

    created_profile = me is None
    if created_profile:
        me = save_profile(event, request.attendee_token, signup_form.cleaned_data["name"], signup_form.field_values())
    try:
        item = add_custom_item(category, me, custom_form.cleaned_data["name"], custom_form.cleaned_data["note"])
    except CustomItemsNotAllowed:
        return HttpResponseBadRequest("This category doesn't take new items.")
    except CustomItemsFull:
        limit = category.custom_item_limit
        if limit == 1:
            message = "Someone just took the last spot for attendees' own items."
        else:
            message = f"Someone just took the last spot. All {limit} spots for attendees' own items are taken."
        return _show_category(request, event, category.pk, me, panel=created_profile, custom_error=message)
    except TooManyCustomItems:
        message = f"You can add up to {settings.MAX_CUSTOM_ITEMS_PER_ATTENDEE} of your own items here."
        return _show_category(request, event, category.pk, me, panel=created_profile, custom_error=message)
    if not request.htmx:
        return _back_to(event, f"item-{item.pk}")
    new_claim = item.claims.first()
    return _show_category(request, event, category.pk, me, panel=created_profile, just_claimed_id=new_claim.pk)


# ---------- "Your info" ----------


@require_http_methods(["GET", "POST"])
def my_profile(request, slug):
    """GET shows the edit form in the panel; POST saves and refreshes the panel and the sheet."""
    event = get_object_or_404(Event, slug=slug)
    me = current_attendee(request, event)

    if request.method == "GET":
        if "cancel" in request.GET:
            if not request.htmx:
                return _back_to(event)
            return HttpResponse(_render_panel(request, event, me))
        form = _profile_form(event, attendee=me)
    else:
        form = _profile_form(event, request.POST, attendee=me)
        if form.is_valid() and (me is not None or not _rate_limited(request, form)):
            token = me.token if me else request.attendee_token
            me = save_profile(event, token, form.cleaned_data["name"], form.field_values(), attendee=me)
            if not request.htmx:
                return _back_to(event)
            # The new name/answers may show on any row, so the sheet comes along as an OOB swap.
            html = _render_panel(request, event, me)
            ctx = sheet_context(request, event, me=me)
            ctx["sheet_oob"] = True
            html += render_to_string("events/partials/sheet.html", ctx, request)
            return HttpResponse(html)

    if not request.htmx:
        return _render_page(request, event, me, panel_editing=True, me_form=form)
    return HttpResponse(_render_panel(request, event, me, panel_editing=True, me_form=form))
