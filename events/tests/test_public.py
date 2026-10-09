import uuid

import pytest
from django.test import Client

from events.models import Claim, CustomField, Event, FieldValue, Item, Category, Attendee
from events.services import claim_slot, save_profile

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def category(event):
    return Category.objects.create(event=event, name="Sides", allow_custom_items=False)


@pytest.fixture
def chips(category):
    return Item.objects.create(category=category, name="Chips", slots=3)


@pytest.fixture
def fields(event):
    phone = CustomField.objects.create(
        event=event, label="Phone", field_type=CustomField.PHONE, required=True, is_public=False
    )
    diet = CustomField.objects.create(event=event, label="Diet", is_public=True)
    return phone, diet


def token_of(client):
    """The attendee token in the client's signed cookie ("<uuid>:<timestamp>:<signature>")."""
    return uuid.UUID(client.cookies["ebs_aid"].value.split(":")[0])


def sign_up(client, event, item, name="Ana", **extra):
    url = f"/{event.slug}/items/{item.pk}/claim/"
    return client.post(url, {"profile": "1", "name": name, **extra}, **HX)


def sheet_html(response):
    html = response.content.decode()
    return html[html.index('id="sheet"') :]


# ---------- landing / event page ----------


def test_landing_attendee_does_not_list_events(client, event):
    r = client.get("/")
    assert r.status_code == 200
    assert "Summer Potluck" not in r.content.decode()
    assert "event link" in r.content.decode()


def test_landing_admin_lists_events(admin_client, event):
    html = admin_client.get("/").content.decode()
    assert "Summer Potluck" in html
    assert "/summer-potluck/" in html
    assert "New event" in html


def test_head_requests_allowed(client, event):
    assert client.head("/").status_code == 200
    assert client.head(f"/{event.slug}/").status_code == 200


def test_event_404(client, db):
    assert client.get("/nope/").status_code == 404


def test_event_page_renders_header_and_sheet(client, event, chips):
    event.location = "Riverside Park"
    event.description = "Bring a chair.\n\nSee you there <b>!</b>"
    event.save()
    html = client.get(f"/{event.slug}/").content.decode()
    assert "Riverside Park" in html
    assert "<p>Bring a chair.</p>" in html
    assert "&lt;b&gt;" in html
    assert 'id="sheet"' in html
    assert "0 of 3 signed up" in html
    assert "ask for your name" in html


# ---------- claiming ----------


def test_first_claim_shows_profile_form(client, event, chips, fields):
    r = client.post(f"/{event.slug}/items/{chips.pk}/claim/", **HX)
    html = r.content.decode()
    assert r.status_code == 200
    assert 'id="item-%d"' % chips.pk in html
    assert 'name="profile"' in html and 'name="name"' in html
    assert f'name="field_{fields[0].pk}"' in html
    assert not Claim.objects.exists()
    assert not Attendee.objects.exists()


def test_profile_submission_creates_attendee_values_and_claim(client, event, chips, fields):
    phone, diet = fields
    r = sign_up(
        client, event, chips, name="Ana", note="Spicy ones",
        **{f"field_{phone.pk}": "555-123-4567", f"field_{diet.pk}": "Vegan"},
    )
    assert r.status_code == 200
    attendee = Attendee.objects.get()
    assert attendee.name == "Ana"
    assert attendee.token == token_of(client)
    assert {v.field.label: v.value for v in attendee.values.all()} == {"Phone": "555-123-4567", "Diet": "Vegan"}
    claim = Claim.objects.get()
    assert claim.attendee == attendee and claim.item == chips and claim.note == "Spicy ones"
    html = r.content.decode()
    assert "just-claimed" in html
    assert 'hx-swap-oob="true"' in html  # "Your info" panel appears
    assert "Edit my info" in html


def test_required_custom_field_enforced(client, event, chips, fields):
    r = sign_up(client, event, chips, name="Ana")
    html = r.content.decode()
    assert r.status_code == 200
    assert "Phone is required for this event." in html
    assert not Attendee.objects.exists() and not Claim.objects.exists()


def test_missing_name_shows_error(client, event, chips):
    r = sign_up(client, event, chips, name="")
    assert "Enter your name" in r.content.decode()
    assert not Attendee.objects.exists()


def test_second_claim_with_profile_claims_directly(client, event, chips, category):
    sign_up(client, event, chips)
    salad = Item.objects.create(category=category, name="Salad", slots=2)
    r = client.post(f"/{event.slug}/items/{salad.pk}/claim/", **HX)
    html = r.content.decode()
    assert Claim.objects.filter(item=salad).count() == 1
    assert "1 of 2 signed up" in html
    assert 'class="slot mine just-claimed"' in html
    assert 'hx-swap-oob' not in html


def test_same_attendee_can_take_another_slot(client, event, chips):
    sign_up(client, event, chips)
    html = client.post(f"/{event.slug}/items/{chips.pk}/claim/", **HX).content.decode()
    assert Claim.objects.filter(item=chips).count() == 2
    assert "I'll bring another" in html


def test_item_full_message(client, event, category):
    soda = Item.objects.create(category=category, name="Soda", slots=1)
    other = save_profile(event, "00000000-0000-0000-0000-000000000001", "Bo", {})
    claim_slot(soda, other)
    sign_up(client, event, Item.objects.create(category=category, name="Ice", slots=5))
    r = client.post(f"/{event.slug}/items/{soda.pk}/claim/", **HX)
    assert "Someone already signed up for Soda." in r.content.decode()
    assert Claim.objects.filter(item=soda).count() == 1

    trays = Item.objects.create(category=category, name="Chips", slots=3)
    for _ in range(3):
        claim_slot(trays, other)
    r = client.post(f"/{event.slug}/items/{trays.pk}/claim/", **HX)
    html = r.content.decode()
    assert "All 3 slots for Chips are taken." in html
    assert "badge full" in html


def test_item_full_before_profile_skips_form(client, event, category):
    soda = Item.objects.create(category=category, name="Soda", slots=1)
    claim_slot(soda, save_profile(event, "00000000-0000-0000-0000-000000000001", "Bo", {}))
    html = client.post(f"/{event.slug}/items/{soda.pk}/claim/", **HX).content.decode()
    assert "Someone already signed up" in html
    assert 'name="profile"' not in html


def test_unlimited_item(client, event, category):
    ice = Item.objects.create(category=category, name="Ice", slots=None)
    sign_up(client, event, ice)
    for _ in range(4):
        client.post(f"/{event.slug}/items/{ice.pk}/claim/", **HX)
    html = client.get(f"/{event.slug}/").content.decode()
    assert Claim.objects.filter(item=ice).count() == 5
    assert "Unlimited · 5 signed up" in html
    assert "I'll bring another" in html

    r = client.post(f"/{event.slug}/items/{ice.pk}/claim/", **HX)  # past MAX_CLAIMS_PER_ITEM (5)
    assert "You&#x27;ve already signed up for Ice 5 times." in r.content.decode()
    assert Claim.objects.filter(item=ice).count() == 5


def test_oversubscribed_badge(client, event, chips):
    v = save_profile(event, "00000000-0000-0000-0000-000000000001", "Bo", {})
    for _ in range(3):
        claim_slot(chips, v)
    Item.objects.filter(pk=chips.pk).update(slots=2)
    assert "Oversubscribed" in client.get(f"/{event.slug}/").content.decode()


def test_open_lines_capped(client, event, category):
    plates = Item.objects.create(category=category, name="Plates", slots=20)
    html = client.get(f"/{event.slug}/").content.decode()
    assert html.count('class="slot open"') == 3
    # Every blank line is its own claim button for the item.
    assert html.count('aria-label="I\'ll bring Plates"') == 3
    assert html.count(f'hx-post="/{event.slug}/items/{plates.pk}/claim/"') == 3
    assert "17 more open" in html


def test_claim_without_htmx_redirects(client, event, chips):
    client.post(f"/{event.slug}/items/{chips.pk}/claim/", {"profile": "1", "name": "Ana"}, **HX)
    r = client.post(f"/{event.slug}/items/{chips.pk}/claim/")
    assert r.status_code == 302
    assert r["Location"] == f"/{event.slug}/#item-{chips.pk}"


def test_claim_without_htmx_first_time_renders_full_page_form(client, event, chips):
    r = client.post(f"/{event.slug}/items/{chips.pk}/claim/")
    html = r.content.decode()
    assert "<h1>Summer Potluck</h1>" in html
    assert 'name="profile"' in html


def test_claim_requires_post(client, event, chips):
    assert client.get(f"/{event.slug}/items/{chips.pk}/claim/").status_code == 405


# ---------- notes and removal permissions ----------


@pytest.fixture
def ana_claim(client, event, chips):
    sign_up(client, event, chips, name="Ana")
    return Claim.objects.get()


def test_owner_edits_note(client, event, ana_claim):
    url = f"/{event.slug}/claims/{ana_claim.pk}/note/"
    form = client.get(url, **HX).content.decode()
    assert "Save note" in form
    r = client.post(url, {"note": "Salt and vinegar"}, **HX)
    ana_claim.refresh_from_db()
    assert ana_claim.note == "Salt and vinegar"
    assert "Salt and vinegar" in r.content.decode()


def test_other_attendee_cannot_edit_or_delete(event, ana_claim):
    other = Client()
    assert other.get(f"/{event.slug}/claims/{ana_claim.pk}/note/", **HX).status_code == 403
    assert other.post(f"/{event.slug}/claims/{ana_claim.pk}/note/", {"note": "x"}, **HX).status_code == 403
    assert other.post(f"/{event.slug}/claims/{ana_claim.pk}/delete/", **HX).status_code == 403
    ana_claim.refresh_from_db()
    assert ana_claim.note == ""


def test_other_attendee_sees_no_actions(event, ana_claim):
    html = Client().get(f"/{event.slug}/").content.decode()
    assert "Ana" in html
    assert "Remove" not in html and "Edit note" not in html and "Add note" not in html


def test_admin_can_edit_and_remove_any_claim(event, ana_claim):
    admin = Client()
    admin.get("/?admin=test-admin-key")
    html = admin.get(f"/{event.slug}/").content.decode()
    assert "Remove Ana from Chips?" in html
    assert admin.post(f"/{event.slug}/claims/{ana_claim.pk}/note/", {"note": "ok"}, **HX).status_code == 200
    r = admin.post(f"/{event.slug}/claims/{ana_claim.pk}/delete/", **HX)
    assert r.status_code == 200
    assert not Claim.objects.exists()


def test_owner_removes_claim(client, event, ana_claim, chips):
    r = client.post(f"/{event.slug}/claims/{ana_claim.pk}/delete/", **HX)
    assert not Claim.objects.exists()
    assert "0 of 3 signed up" in r.content.decode()
    assert Item.objects.filter(pk=chips.pk).exists()


def test_ids_scoped_to_event(client, event, ana_claim, chips, category):
    other_event = Event.objects.create(title="Other", slug="other")
    assert client.post(f"/other/items/{chips.pk}/claim/", **HX).status_code == 404
    assert client.post(f"/other/claims/{ana_claim.pk}/delete/", **HX).status_code == 404
    assert client.get(f"/other/claims/{ana_claim.pk}/note/", **HX).status_code == 404
    category.allow_custom_items = True
    category.save()
    assert client.post(f"/other/categories/{category.pk}/custom-item/", {"item-name": "x"}, **HX).status_code == 404
    assert Claim.objects.count() == 1 and other_event.categories.count() == 0


# ---------- privacy ----------


def test_private_values_never_on_sheet(client, event, chips, fields):
    phone, diet = fields
    sign_up(client, event, chips, name="Ana", **{f"field_{phone.pk}": "555-867-5309", f"field_{diet.pk}": "Vegan"})

    other_html = Client().get(f"/{event.slug}/").content.decode()
    assert "Ana" in other_html
    assert "Diet: Vegan" in other_html
    assert "555-867-5309" not in other_html

    owner = client.get(f"/{event.slug}/")
    assert "555-867-5309" in owner.content.decode()  # their own "Your info" panel
    assert "555-867-5309" not in sheet_html(owner)
    assert "Diet: Vegan" in sheet_html(owner)

    admin = Client()
    admin.get("/?admin=test-admin-key")
    assert "555-867-5309" not in admin.get(f"/{event.slug}/").content.decode()

    item_partial = client.post(f"/{event.slug}/items/{chips.pk}/claim/", **HX).content.decode()
    assert "555-867-5309" not in item_partial


# ---------- custom items ----------


def test_custom_item_flow_for_new_attendee(client, event, category, fields):
    phone, _ = fields
    category.allow_custom_items = True
    category.save()
    url = f"/{event.slug}/categories/{category.pk}/custom-item/"

    form = client.get(url, **HX).content.decode()
    assert 'name="item-name"' in form and 'name="name"' in form and f'name="field_{phone.pk}"' in form

    r = client.post(url, {"item-name": "Lemon bars", "name": "Cleo"}, **HX)  # missing required phone
    assert "Phone is required" in r.content.decode()
    assert not Item.objects.filter(is_custom=True).exists()

    data = {"item-name": "Lemon bars", "item-note": "Nut-free", "name": "Cleo", f"field_{phone.pk}": "555 111 2222"}
    r = client.post(url, data, **HX)
    html = r.content.decode()
    item = Item.objects.get(is_custom=True)
    assert item.name == "Lemon bars" and item.slots == 1
    assert item.created_by.name == "Cleo"
    assert item.claims.get().note == "Nut-free"
    assert f'id="category-{category.pk}"' in html
    assert "Lemon bars" in html and "just-claimed" in html
    assert 'id="my-info" aria-labelledby="my-info-title" style="margin-bottom:2.5rem" hx-swap-oob="true"' in html


def test_custom_item_with_existing_profile(client, event, category, chips):
    category.allow_custom_items = True
    category.save()
    sign_up(client, event, chips)
    url = f"/{event.slug}/categories/{category.pk}/custom-item/"
    assert 'name="field_' not in client.get(url, **HX).content.decode()
    client.post(url, {"item-name": "Brownies"}, **HX)
    item = Item.objects.get(is_custom=True)
    assert item.claims.get().attendee.name == "Ana"


def test_custom_items_per_person_limit_message(client, event, category, chips, settings):
    settings.MAX_CUSTOM_ITEMS_PER_ATTENDEE = 1
    category.allow_custom_items = True
    category.save()
    sign_up(client, event, chips)
    url = f"/{event.slug}/categories/{category.pk}/custom-item/"
    client.post(url, {"item-name": "Brownies"}, **HX)
    r = client.post(url, {"item-name": "Cookies"}, **HX)
    assert "You can add up to 1 of your own items here." in r.content.decode()
    assert list(Item.objects.filter(is_custom=True).values_list("name", flat=True)) == ["Brownies"]


def test_new_attendees_rate_limited_per_ip(event, category, settings):
    settings.NEW_ATTENDEES_PER_HOUR = 2
    chips = Item.objects.create(category=category, name="Chips", slots=None)
    ip = {"REMOTE_ADDR": "203.0.113.7"}
    for name in ("Ana", "Bo"):
        assert Client(**ip).post(f"/{event.slug}/items/{chips.pk}/claim/", {"profile": "1", "name": name}, **HX)
    blocked = Client(**ip)
    r = blocked.post(f"/{event.slug}/items/{chips.pk}/claim/", {"profile": "1", "name": "Cy"}, **HX)
    assert "Too many new signups from your network. Try again later." in r.content.decode()
    assert 'name="profile"' in r.content.decode()  # the form stays open
    r = blocked.post(f"/{event.slug}/me/", {"name": "Cy"}, **HX)
    assert "Too many new signups" in r.content.decode()
    assert sorted(Attendee.objects.values_list("name", flat=True)) == ["Ana", "Bo"]

    # Another network is unaffected; behind a proxy the first X-Forwarded-For entry counts.
    sign_up(Client(REMOTE_ADDR="198.51.100.1"), event, chips, name="Dee")
    settings.BEHIND_PROXY = True
    sign_up(Client(**ip, HTTP_X_FORWARDED_FOR="198.51.100.2, 10.0.0.1"), event, chips, name="Eve")
    assert Attendee.objects.count() == 4


def test_custom_item_disallowed_category(client, event, category):
    url = f"/{event.slug}/categories/{category.pk}/custom-item/"
    assert client.get(url, **HX).status_code == 404
    assert client.post(url, {"item-name": "Brownies", "name": "Ana"}, **HX).status_code == 404
    assert "+ Bring something else" not in client.get(f"/{event.slug}/").content.decode()


def test_removing_last_claim_on_custom_item_deletes_it(client, event, category, chips):
    category.allow_custom_items = True
    category.save()
    sign_up(client, event, chips)
    client.post(f"/{event.slug}/categories/{category.pk}/custom-item/", {"item-name": "Brownies"}, **HX)
    item = Item.objects.get(is_custom=True)
    r = client.post(f"/{event.slug}/claims/{item.claims.get().pk}/delete/", **HX)
    assert not Item.objects.filter(pk=item.pk).exists()
    assert r["HX-Retarget"] == f"#category-{category.pk}"
    assert r["HX-Reswap"] == "outerHTML"
    html = r.content.decode()
    assert f'id="category-{category.pk}"' in html and "Brownies" not in html


# ---------- profile edit ----------


def test_profile_edit_updates_name_on_sheet(client, event, chips, fields):
    phone, diet = fields
    sign_up(client, event, chips, name="Ana", **{f"field_{phone.pk}": "555-123-4567"})
    url = f"/{event.slug}/me/"
    form = client.get(url, **HX).content.decode()
    assert 'value="Ana"' in form and "555-123-4567" in form and "Save my info" in form

    r = client.post(url, {"name": "Ana Lopez", f"field_{phone.pk}": "555-000-1111", f"field_{diet.pk}": "Keto"}, **HX)
    html = r.content.decode()
    assert '<div id="sheet" hx-swap-oob="true">' in html
    assert "Ana Lopez" in sheet_html(r)
    assert "Diet: Keto" in sheet_html(r)
    assert "555-000-1111" not in sheet_html(r)
    attendee = Attendee.objects.get()
    assert attendee.name == "Ana Lopez"
    assert FieldValue.objects.get(attendee=attendee, field=phone).value == "555-000-1111"
    assert Attendee.objects.count() == 1

    page = client.get(f"/{event.slug}/").content.decode()
    assert "Ana Lopez" in page


def test_profile_edit_validation(client, event, chips, fields):
    sign_up(client, event, chips, name="Ana", **{f"field_{fields[0].pk}": "555-123-4567"})
    r = client.post(f"/{event.slug}/me/", {"name": "", f"field_{fields[0].pk}": "abc"}, **HX)
    html = r.content.decode()
    assert "Enter your name" in html and "Enter a phone number, like 555-123-4567." in html
    assert Attendee.objects.get().name == "Ana"


def test_profile_edit_not_htmx_redirects(client, event, chips):
    sign_up(client, event, chips, name="Ana")
    r = client.post(f"/{event.slug}/me/", {"name": "Bea"})
    assert r.status_code == 302
    assert Attendee.objects.get().name == "Bea"


# ---------- performance ----------


def test_sheet_query_count_bounded(client, event, fields, django_assert_max_num_queries):
    phone, diet = fields
    attendees = [
        save_profile(event, f"00000000-0000-0000-0000-00000000000{i}", f"V{i}", {phone: "555-123-4567", diet: "Veg"})
        for i in range(1, 6)
    ]
    for g in range(4):
        category = Category.objects.create(event=event, name=f"G{g}", allow_custom_items=bool(g % 2))
        for i in range(5):
            item = Item.objects.create(category=category, name=f"I{g}{i}", slots=None if i == 0 else 4)
            for v in attendees[: i + 1][:4]:
                claim_slot(item, v)
    sign_up(client, event, Item.objects.first(), name="Me", **{f"field_{phone.pk}": "555-123-4567"})

    with django_assert_max_num_queries(10):
        r = client.get(f"/{event.slug}/")
    assert r.status_code == 200


# ---------- attendee-added item cap ----------


def test_new_categories_let_attendees_add_up_to_10(event):
    category = Category.objects.create(event=event, name="Mains")
    assert (category.allow_custom_items, category.custom_item_limit) == (True, 10)


def test_custom_item_cap_blocks_extra_items(client, event, category):
    category.allow_custom_items = True
    category.custom_item_limit = 2
    category.save()
    url = f"/{event.slug}/categories/{category.pk}/custom-item/"

    client.post(url, {"item-name": "Lasagna", "name": "Ana"}, **HX)
    html = client.get(f"/{event.slug}/").content.decode()
    assert "1 of 2 spots left" in html
    assert "+ Bring something else" in html

    other = Client()
    other.post(url, {"item-name": "Enchiladas", "name": "Bo"}, **HX)
    html = other.get(f"/{event.slug}/").content.decode()
    assert "All 2 spots for attendees' own items are taken." in html
    assert "+ Bring something else" not in html

    third = Client()
    r = third.post(url, {"item-name": "Curry", "name": "Cy"}, **HX)
    assert "Someone just took the last spot" in r.content.decode()
    assert Item.objects.filter(is_custom=True).count() == 2


def test_unlimited_custom_items(client, event, category):
    category.allow_custom_items = True
    category.custom_item_limit = None
    category.save()
    url = f"/{event.slug}/categories/{category.pk}/custom-item/"
    for n in range(12):
        Client().post(url, {"item-name": f"Dish {n}", "name": f"P{n}"}, **HX)
    assert Item.objects.filter(is_custom=True).count() == 12
    assert "spots left" not in client.get(f"/{event.slug}/").content.decode()


def test_pages_ask_search_engines_not_to_index(client, event):
    for url in ("/", event.get_absolute_url(), "/no-such-event/"):
        response = client.get(url)
        assert response["X-Robots-Tag"] == "noindex, nofollow", url
    assert '<meta name="robots" content="noindex, nofollow">' in client.get(event.get_absolute_url()).content.decode()
