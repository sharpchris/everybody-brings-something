import re

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from events.models import Claim, CustomField, Event, FieldValue, Item, Category, Attendee
from events.services import add_custom_item, claim_slot

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def category(event):
    return Category.objects.create(event=event, name="Mains", position=1, allow_custom_items=False)


@pytest.fixture
def item(category):
    return Item.objects.create(category=category, name="Lasagna", slots=2, position=1)


@pytest.fixture
def field(event):
    return CustomField.objects.create(event=event, label="Phone", field_type="phone", position=1)


@pytest.fixture
def attendee(event):
    return Attendee.objects.create(event=event, name="Ana")


@pytest.fixture
def other_event(db):
    other = Event.objects.create(title="Other", slug="other")
    g = Category.objects.create(event=other, name="Drinks")
    i = Item.objects.create(category=g, name="Soda", slots=1)
    f = CustomField.objects.create(event=other, label="Email", field_type="email")
    v = Attendee.objects.create(event=other, name="Zed")
    c = Claim.objects.create(item=i, attendee=v)
    return {"event": other, "category": g, "item": i, "field": f, "attendee": v, "claim": c}


def all_manage_urls(event, category, item, field, attendee, claim):
    s = event.slug
    return [
        reverse("manage_event_new"),
        reverse("manage_event_settings", args=[s]),
        reverse("manage_event_delete", args=[s]),
        reverse("manage_event_responses", args=[s]),
        reverse("manage_field_add", args=[s]),
        reverse("manage_field_edit", args=[s, field.pk]),
        reverse("manage_field_delete", args=[s, field.pk]),
        reverse("manage_field_move", args=[s, field.pk, "up"]),
        reverse("manage_field_toggle", args=[s, field.pk, "public"]),
        reverse("manage_category_add", args=[s]),
        reverse("manage_category_edit", args=[s, category.pk]),
        reverse("manage_category_delete", args=[s, category.pk]),
        reverse("manage_category_move", args=[s, category.pk, "up"]),
        reverse("manage_category_toggle_custom", args=[s, category.pk]),
        reverse("manage_item_add", args=[s, category.pk]),
        reverse("manage_item_edit", args=[s, item.pk]),
        reverse("manage_item_delete", args=[s, item.pk]),
        reverse("manage_item_move", args=[s, item.pk, "up"]),
        reverse("manage_attendee_edit", args=[s, attendee.pk]),
        reverse("manage_attendee_delete", args=[s, attendee.pk]),
        reverse("manage_claim_note", args=[s, claim.pk]),
        reverse("manage_claim_delete", args=[s, claim.pk]),
    ]


def item_data(**overrides):
    return {"name": "Salad", "description": "", "slots": "3", **overrides}


# ---------- access ----------


def test_non_admin_gets_404_everywhere(client, event, category, item, field, attendee):
    claim = Claim.objects.create(item=item, attendee=attendee)
    for url in all_manage_urls(event, category, item, field, attendee, claim):
        assert client.get(url).status_code == 404, url
        assert client.post(url, {"name": "x", "title": "x"}).status_code == 404, url
    assert Event.objects.filter(pk=event.pk).exists()
    assert Item.objects.filter(pk=item.pk).exists()


def test_ids_from_another_event_404(admin_client, event, other_event):
    o = other_event
    urls = all_manage_urls(event, o["category"], o["item"], o["field"], o["attendee"], o["claim"])
    scoped = [u for u in urls if any(f"/{part}/" in u for part in ("fields", "categories", "items", "attendees", "claims"))]
    scoped = [u for u in scoped if not u.endswith("/fields/add/") and not u.endswith("/categories/add/")]
    for url in scoped:
        assert admin_client.post(url, {"name": "Hacked", "label": "Hacked", "field_type": "text"}).status_code == 404, url
    o["item"].refresh_from_db()
    assert o["item"].name == "Soda"
    assert Claim.objects.filter(pk=o["claim"].pk).exists()
    assert Attendee.objects.filter(pk=o["attendee"].pk).exists()


def test_mutating_endpoints_reject_get(admin_client, event, category, item):
    assert admin_client.get(reverse("manage_item_delete", args=[event.slug, item.pk])).status_code == 405
    assert admin_client.get(reverse("manage_event_delete", args=[event.slug])).status_code == 405
    assert Item.objects.filter(pk=item.pk).exists()


# ---------- events ----------


def test_create_event_blank_slug_autogenerates(admin_client, db):
    Event.objects.create(title="Taken", slug="fall-picnic")
    r = admin_client.post(reverse("manage_event_new"), {"title": "Fall Picnic", "slug": ""})
    event = Event.objects.get(title="Fall Picnic")
    assert re.fullmatch(r"fall-picnic-[a-z2-9]{4}", event.slug)
    assert r.status_code == 302
    assert r["Location"] == event.get_absolute_url()


def test_create_event_with_custom_slug(admin_client, db):
    admin_client.post(reverse("manage_event_new"), {"title": "BBQ", "slug": "Backyard-BBQ"})
    assert Event.objects.get(title="BBQ").slug == "backyard-bbq"


@pytest.mark.parametrize("slug", ["summer-potluck", "manage", "health"])
def test_create_event_rejects_taken_or_reserved_slug(admin_client, event, slug):
    r = admin_client.post(reverse("manage_event_new"), {"title": "Another", "slug": slug})
    assert r.status_code == 200
    assert not Event.objects.filter(title="Another").exists()
    assert r.context["form"].errors["slug"]


def test_new_event_page_renders(admin_client, db):
    r = admin_client.get(reverse("manage_event_new"))
    assert r.status_code == 200
    assert b"Create event" in r.content


def test_settings_slug_edit_changes_url(admin_client, event):
    url = reverse("manage_event_settings", args=[event.slug])
    r = admin_client.post(url, {"title": "Summer Potluck", "slug": "summer-bash"})
    assert r.status_code == 302
    assert r["Location"] == reverse("manage_event_settings", args=["summer-bash"])
    event.refresh_from_db()
    assert event.slug == "summer-bash"
    assert event.get_absolute_url() == "/summer-bash/"
    assert admin_client.get(url).status_code == 404


def test_settings_slug_conflict_shows_error(admin_client, event):
    Event.objects.create(title="Other", slug="other")
    url = reverse("manage_event_settings", args=[event.slug])
    r = admin_client.post(url, {"title": "Summer Potluck", "slug": "other"})
    assert r.status_code == 200
    assert r.context["form"].errors["slug"]
    # Links on the page still point at the real slug.
    assert reverse("manage_event_responses", args=["summer-potluck"]).encode() in r.content
    event.refresh_from_db()
    assert event.slug == "summer-potluck"


def test_settings_page_shows_links_and_fields(admin_client, event, field):
    r = admin_client.get(reverse("manage_event_settings", args=[event.slug]))
    body = r.content.decode()
    assert "Phone" in body
    assert 'class="badge private"' in body
    assert "Visible to other attendees" in body
    assert reverse("manage_event_responses", args=[event.slug]) in body
    assert event.get_absolute_url() in body


def test_event_delete(admin_client, event, item):
    r = admin_client.post(reverse("manage_event_delete", args=[event.slug]))
    assert r.status_code == 302
    assert r["Location"] == reverse("landing")
    assert not Event.objects.exists()
    assert not Item.objects.exists()


def test_event_delete_htmx_client_redirects(admin_client, event):
    r = admin_client.post(reverse("manage_event_delete", args=[event.slug]), **HX)
    assert r["HX-Redirect"] == reverse("landing")


# ---------- custom fields ----------


def test_field_add_edit_delete(admin_client, event):
    r = admin_client.post(
        reverse("manage_field_add", args=[event.slug]),
        {"label": "Dietary needs", "field_type": "text", "help_text": ""},
        **HX,
    )
    assert r.status_code == 200
    f = CustomField.objects.get(event=event)
    assert f.label == "Dietary needs"
    assert f.is_public is False
    assert 'id="fields"' in r.content.decode()

    edit_url = reverse("manage_field_edit", args=[event.slug, f.pk])
    assert b"Save field" in admin_client.get(edit_url, **HX).content
    admin_client.post(edit_url, {"label": "Contact email", "field_type": "email", "required": "on", "is_public": "on"}, **HX)
    f.refresh_from_db()
    assert (f.label, f.field_type, f.required, f.is_public) == ("Contact email", "email", True, True)

    admin_client.post(reverse("manage_field_delete", args=[event.slug, f.pk]), **HX)
    assert not CustomField.objects.exists()


def test_field_add_invalid_shows_errors(admin_client, event):
    r = admin_client.post(reverse("manage_field_add", args=[event.slug]), {"label": "", "field_type": "text"}, **HX)
    assert r.status_code == 200
    assert r.context["field_form"].errors["label"]
    assert not CustomField.objects.exists()


def test_field_toggles(admin_client, event, field):
    admin_client.post(reverse("manage_field_toggle", args=[event.slug, field.pk, "required"]), **HX)
    admin_client.post(reverse("manage_field_toggle", args=[event.slug, field.pk, "public"]), **HX)
    field.refresh_from_db()
    assert field.required and field.is_public
    assert admin_client.post(reverse("manage_field_toggle", args=[event.slug, field.pk, "label"])).status_code == 404


def test_field_reorder(admin_client, event, field):
    second = CustomField.objects.create(event=event, label="Email", position=2)
    admin_client.post(reverse("manage_field_move", args=[event.slug, second.pk, "up"]), **HX)
    assert list(event.fields.values_list("label", flat=True)) == ["Email", "Phone"]
    # Moving the first one up is a no-op.
    admin_client.post(reverse("manage_field_move", args=[event.slug, second.pk, "up"]), **HX)
    assert list(event.fields.values_list("label", flat=True)) == ["Email", "Phone"]
    admin_client.post(reverse("manage_field_move", args=[event.slug, second.pk, "down"]), **HX)
    assert list(event.fields.values_list("label", flat=True)) == ["Phone", "Email"]
    assert admin_client.post(reverse("manage_field_move", args=[event.slug, second.pk, "sideways"])).status_code == 404


def test_field_non_htmx_redirects_to_settings(admin_client, event, field):
    r = admin_client.post(reverse("manage_field_toggle", args=[event.slug, field.pk, "public"]))
    assert r.status_code == 302
    assert r["Location"] == reverse("manage_event_settings", args=[event.slug])


def test_make_public_confirms_when_private_answers_exist(admin_client, event, field, attendee):
    FieldValue.objects.create(attendee=attendee, field=field, value="555-123-4567")
    page = admin_client.get(reverse("manage_event_settings", args=[event.slug])).content.decode()
    assert "1 person answered “Phone” while it was private. Make their answers visible to everyone?" in page
    assert """hx-vals='{"confirm": "1"}'""" in page

    url = reverse("manage_field_toggle", args=[event.slug, field.pk, "public"])
    r = admin_client.post(url, **HX)
    assert "confirm before showing their answers" in r.content.decode()
    field.refresh_from_db()
    assert not field.is_public

    admin_client.post(url, {"confirm": "1"}, **HX)
    field.refresh_from_db()
    assert field.is_public


def test_field_edit_make_public_needs_acknowledgement(admin_client, event, field, attendee):
    FieldValue.objects.create(attendee=attendee, field=field, value="555-123-4567")
    url = reverse("manage_field_edit", args=[event.slug, field.pk])
    data = {"label": "Phone", "field_type": "phone", "is_public": "on"}
    r = admin_client.post(url, data, **HX)
    assert "Confirm that earlier private answers will become visible" in r.content.decode()
    field.refresh_from_db()
    assert not field.is_public

    admin_client.post(url, {**data, "label": "Mobile"}, **HX)  # private edits need no acknowledgement...
    admin_client.post(url, {**data, "confirm_public": "on"}, **HX)  # ...making it public does
    field.refresh_from_db()
    assert field.is_public


def test_field_type_locked_after_answers(admin_client, event, field, attendee):
    url = reverse("manage_field_edit", args=[event.slug, field.pk])
    assert "change the type" not in admin_client.get(url, **HX).content.decode()
    FieldValue.objects.create(attendee=attendee, field=field, value="555-123-4567")
    html = admin_client.get(url, **HX).content.decode()
    assert "Can&#x27;t change the type after people have answered. Add a new field instead." in html
    assert re.search(r'<select name="field_type"[^>]*disabled', html)
    admin_client.post(url, {"label": "Phone", "field_type": "checkbox"}, **HX)
    field.refresh_from_db()
    assert field.field_type == "phone"


# ---------- categories ----------


def test_category_add_returns_sheet(admin_client, event, category):
    r = admin_client.post(
        reverse("manage_category_add", args=[event.slug]),
        {"name": "Desserts", "allow_custom_items": "on", "custom_item_limit": "10"},
        **HX,
    )
    assert r.status_code == 200
    body = r.content.decode()
    assert 'id="sheet"' in body
    assert "Desserts" in body
    new = Category.objects.get(name="Desserts")
    assert new.position == category.position + 1
    assert (new.allow_custom_items, new.custom_item_limit) == (True, 10)


def test_category_add_invalid_retargets_form(admin_client, event):
    r = admin_client.post(reverse("manage_category_add", args=[event.slug]), {"name": ""}, **HX)
    assert r["HX-Retarget"] == "#category-form-new"
    assert r["HX-Reswap"] == "outerHTML"
    assert not Category.objects.exists()


def test_category_add_non_htmx_redirects(admin_client, event):
    r = admin_client.post(reverse("manage_category_add", args=[event.slug]), {"name": "Sides"})
    assert r.status_code == 302
    assert r["Location"] == event.get_absolute_url()


def test_category_edit_toggle_delete(admin_client, event, category, item):
    edit_url = reverse("manage_category_edit", args=[event.slug, category.pk])
    r = admin_client.get(edit_url, **HX)
    assert b'id="category-form-%d"' % category.pk in r.content
    admin_client.post(edit_url, {"name": "Main dishes", "description": "Hot food", "custom_item_limit": "5"}, **HX)
    category.refresh_from_db()
    assert (category.name, category.description, category.custom_item_limit) == ("Main dishes", "Hot food", 5)

    admin_client.post(reverse("manage_category_toggle_custom", args=[event.slug, category.pk]), **HX)
    category.refresh_from_db()
    assert category.allow_custom_items is True

    admin_client.post(reverse("manage_category_delete", args=[event.slug, category.pk]), **HX)
    assert not Category.objects.exists()
    assert not Item.objects.exists()


def test_category_edit_non_htmx_get_renders_page(admin_client, event, category):
    r = admin_client.get(reverse("manage_category_edit", args=[event.slug, category.pk]))
    assert r.status_code == 200
    assert b"hx-post" not in r.content.split(b'id="category-form-')[1].split(b">")[0]


def test_category_reorder(admin_client, event, category):
    second = Category.objects.create(event=event, name="Sides", position=2)
    admin_client.post(reverse("manage_category_move", args=[event.slug, second.pk, "up"]), **HX)
    assert list(event.categories.values_list("name", flat=True)) == ["Sides", "Mains"]
    admin_client.post(reverse("manage_category_move", args=[event.slug, second.pk, "down"]), **HX)
    assert list(event.categories.values_list("name", flat=True)) == ["Mains", "Sides"]


def test_category_move_arrows_disabled_at_the_ends(admin_client, event, category):
    second = Category.objects.create(event=event, name="Sides", position=2)

    def arrows(html, name):
        return [
            re.search(rf'aria-label="Move {name} {d}"[^>]*>', html).group(0).count("disabled") for d in ("up", "down")
        ]

    sheet = admin_client.get(f"/{event.slug}/").content.decode()
    assert arrows(sheet, "Mains") == [1, 0] and arrows(sheet, "Sides") == [0, 1]
    single = admin_client.get(f"/{event.slug}/categories/{second.pk}/", **HX).content.decode()
    assert arrows(single, "Sides") == [0, 1]


def test_reorder_handles_tied_positions(admin_client, event):
    a = Category.objects.create(event=event, name="A")
    b = Category.objects.create(event=event, name="B")
    admin_client.post(reverse("manage_category_move", args=[event.slug, b.pk, "up"]), **HX)
    assert list(event.categories.values_list("name", flat=True)) == ["B", "A"]
    assert a.pk != b.pk


# ---------- items ----------


def test_item_add(admin_client, event, category, item):
    url = reverse("manage_item_add", args=[event.slug, category.pk])
    assert b'id="item-form-new-%d"' % category.pk in admin_client.get(url, **HX).content
    r = admin_client.post(url, item_data(), **HX)
    assert 'id="sheet"' in r.content.decode()
    new = Item.objects.get(name="Salad")
    assert (new.category, new.slots, new.position) == (category, 3, item.position + 1)


def test_item_add_unlimited(admin_client, event, category):
    admin_client.post(
        reverse("manage_item_add", args=[event.slug, category.pk]), item_data(slots="", unlimited="on"), **HX
    )
    assert Item.objects.get(name="Salad").slots is None


def test_item_add_requires_slots_or_unlimited(admin_client, event, category):
    r = admin_client.post(reverse("manage_item_add", args=[event.slug, category.pk]), item_data(slots=""), **HX)
    assert r["HX-Retarget"] == f"#item-form-new-{category.pk}"
    assert b"tick Unlimited" in r.content
    assert not Item.objects.filter(name="Salad").exists()


def test_item_edit_toggle_unlimited_and_back(admin_client, event, item):
    url = reverse("manage_item_edit", args=[event.slug, item.pk])
    admin_client.post(url, item_data(name="Big lasagna", unlimited="on"), **HX)
    item.refresh_from_db()
    assert (item.name, item.slots) == ("Big lasagna", None)
    admin_client.post(url, item_data(name="Big lasagna", slots="4"), **HX)
    item.refresh_from_db()
    assert item.slots == 4


def test_item_slots_can_drop_below_claims(admin_client, event, item):
    for name in ("A", "B"):
        claim_slot(item, Attendee.objects.create(event=event, name=name))
    admin_client.post(reverse("manage_item_edit", args=[event.slug, item.pk]), item_data(slots="1"), **HX)
    item.refresh_from_db()
    assert item.slots == 1
    assert item.claims.count() == 2


def test_item_delete_and_reorder(admin_client, event, category, item):
    second = Item.objects.create(category=category, name="Curry", slots=1, position=2)
    admin_client.post(reverse("manage_item_move", args=[event.slug, second.pk, "up"]), **HX)
    assert list(category.items.values_list("name", flat=True)) == ["Curry", "Lasagna"]
    admin_client.post(reverse("manage_item_delete", args=[event.slug, item.pk]), **HX)
    assert list(category.items.values_list("name", flat=True)) == ["Curry"]


def test_item_controls_partial_mentions_signup_count(rf, event, item, attendee):
    claim_slot(item, attendee)
    request = rf.get("/")
    html = render_to_string(
        "events/manage/partials/item_controls.html",
        {"event": event, "category": item.category, "item": item},
        request=request,
    )
    assert reverse("manage_item_edit", args=[event.slug, item.pk]) in html
    assert "1 signup will be removed too" in html


def test_sheet_partial_includes_admin_controls(admin_client, event, category):
    r = admin_client.post(reverse("manage_category_toggle_custom", args=[event.slug, category.pk]), **HX)
    body = r.content.decode()
    assert reverse("manage_item_add", args=[event.slug, category.pk]) in body
    assert re.search(r'role="switch"[^>]*\bchecked\b', body)  # toggle now on
    assert reverse("manage_category_add", args=[event.slug]) in body


# ---------- responses ----------


def test_responses_show_private_values(admin_client, event, item, field, attendee):
    FieldValue.objects.create(attendee=attendee, field=field, value="555-0100")
    claim_slot(item, attendee, note="Vegetarian")
    r = admin_client.get(reverse("manage_event_responses", args=[event.slug]))
    body = r.content.decode()
    assert "555-0100" in body
    assert "Ana" in body
    assert "Lasagna" in body
    assert "Vegetarian" in body
    assert 'class="table-scroll"' in body
    assert 'class="badge private"' in body


def test_responses_empty_state(admin_client, event):
    r = admin_client.get(reverse("manage_event_responses", args=[event.slug]))
    assert b"No one has signed up yet" in r.content


def test_admin_edits_attendee_profile(admin_client, event, field, attendee):
    url = reverse("manage_attendee_edit", args=[event.slug, attendee.pk])
    assert admin_client.get(url).status_code == 200
    r = admin_client.post(url, {"name": "Ana B", field.form_key: "555-0199"})
    assert r.status_code == 302
    attendee.refresh_from_db()
    assert attendee.name == "Ana B"
    assert FieldValue.objects.get(attendee=attendee, field=field).value == "555-0199"
    assert Attendee.objects.count() == 1


def test_admin_edit_attendee_validates(admin_client, event, field, attendee):
    r = admin_client.post(reverse("manage_attendee_edit", args=[event.slug, attendee.pk]), {"name": "", field.form_key: "x"})
    assert r.status_code == 200
    assert r.context["form"].errors


def test_admin_deletes_claim(admin_client, event, item, attendee):
    claim = claim_slot(item, attendee)
    r = admin_client.post(reverse("manage_claim_delete", args=[event.slug, claim.pk]), **HX)
    assert 'id="responses"' in r.content.decode()
    assert not Claim.objects.exists()
    assert Item.objects.filter(pk=item.pk).exists()


def test_deleting_last_claim_removes_custom_item(admin_client, event, category, attendee):
    category.allow_custom_items = True
    category.save()
    custom = add_custom_item(category, attendee, "Brownies")
    claim = custom.claims.get()
    admin_client.post(reverse("manage_claim_delete", args=[event.slug, claim.pk]), **HX)
    assert not Item.objects.filter(pk=custom.pk).exists()


def test_admin_deletes_attendee_and_their_custom_items(admin_client, event, category, item, attendee):
    category.allow_custom_items = True
    category.save()
    custom = add_custom_item(category, attendee, "Brownies")
    claim_slot(item, attendee)
    r = admin_client.post(reverse("manage_attendee_delete", args=[event.slug, attendee.pk]))
    assert r.status_code == 302
    assert not Attendee.objects.exists()
    assert not Claim.objects.exists()
    assert not Item.objects.filter(pk=custom.pk).exists()
    assert Item.objects.filter(pk=item.pk).exists()


def test_admin_edits_claim_note(admin_client, event, item, attendee):
    claim = claim_slot(item, attendee, note="old")
    url = reverse("manage_claim_note", args=[event.slug, claim.pk])
    assert b"Save note" in admin_client.get(url, **HX).content
    r = admin_client.post(url, {"note": "  Gluten free  "}, **HX)
    assert 'id="responses"' in r.content.decode()
    claim.refresh_from_db()
    assert claim.note == "Gluten free"



# ---------- share link auto-fill ----------


def test_share_link_label_and_no_auto_note(admin_client):
    body = admin_client.get("/manage/new/").content.decode()
    assert "Share link" in body
    assert "Leave blank" not in body
    assert "data-slug-source" in body and "data-slug-target" in body
    assert "data-slug-locked" not in body


def test_auto_filled_share_link_gets_suffix_when_taken(admin_client, event):
    r = admin_client.post(
        "/manage/new/", {"title": "Summer Potluck", "slug": event.slug, "slug_auto": "True"}
    )
    assert r.status_code == 302
    assert Event.objects.filter(slug=f"{event.slug}-2").exists()


def test_hand_typed_share_link_that_is_taken_shows_error(admin_client, event):
    r = admin_client.post("/manage/new/", {"title": "Another", "slug": event.slug})
    assert r.status_code == 200
    assert Event.objects.count() == 1


def test_settings_share_link_is_locked(admin_client, event):
    body = admin_client.get(f"/manage/{event.slug}/settings/").content.decode()
    assert "data-slug-locked" in body



def test_category_form_requires_a_cap_while_attendees_can_add(admin_client, event, category):
    edit_url = reverse("manage_category_edit", args=[event.slug, category.pk])
    r = admin_client.post(edit_url, {"name": "Mains", "allow_custom_items": "on", "custom_item_limit": ""}, **HX)
    assert "or tick No limit" in r.content.decode()

    admin_client.post(edit_url, {"name": "Mains", "allow_custom_items": "on", "unlimited_custom": "on"}, **HX)
    category.refresh_from_db()
    assert category.allow_custom_items and category.custom_item_limit is None


def test_new_event_with_custom_fields(admin_client, db):
    data = {
        "title": "Field Day",
        "fields-TOTAL_FORMS": "3",
        "fields-INITIAL_FORMS": "0",
        "fields-0-label": "Phone",
        "fields-0-field_type": "phone",
        "fields-0-required": "on",
        "fields-1-label": "Bringing guests?",
        "fields-1-field_type": "text",
        "fields-1-is_public": "on",
        "fields-2-label": "",  # blank row is skipped
        "fields-2-field_type": "text",
    }
    r = admin_client.post(reverse("manage_event_new"), data)
    assert r.status_code == 302
    event = Event.objects.get(title="Field Day")
    fields = list(event.fields.values_list("label", "field_type", "required", "is_public", "position"))
    assert fields == [("Phone", "phone", True, False, 1), ("Bringing guests?", "text", False, True, 2)]


# ---------- guest view ----------


def test_guest_view_hides_admin_until_exit(admin_client, event):
    page = event.get_absolute_url()
    r = admin_client.post(reverse("manage_guest_view"), {"next": page})
    assert r.status_code == 302 and r["Location"] == page

    body = admin_client.get(page).content.decode()
    assert "Exit guest view" in body
    assert "admin-bar" not in body and "Copy share link" not in body
    assert admin_client.get(reverse("manage_event_settings", args=[event.slug])).status_code == 404

    r = admin_client.post(reverse("manage_guest_view_exit"), {"next": page})
    assert r["Location"] == page
    body = admin_client.get(page).content.decode()
    assert "Exit guest view" not in body and "Copy share link" in body


def test_guest_view_needs_admin_and_stays_on_site(admin_client, event):
    attendee = Client()  # admin_client wraps the `client` fixture, so use a fresh one
    assert attendee.post(reverse("manage_guest_view"), {"next": "/"}).status_code == 404
    assert attendee.post(reverse("manage_guest_view_exit"), {"next": "/"}).status_code == 404
    r = admin_client.post(reverse("manage_guest_view"), {"next": "https://evil.example/"})
    assert r["Location"] == reverse("landing")
