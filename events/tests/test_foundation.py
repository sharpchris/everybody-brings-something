import re
import threading
import uuid

import pytest
from django.db import connection
from django.test import Client

from events.forms import build_profile_form
from events.models import Claim, CustomField, Event, Item, Category, Attendee
from events.services import (
    CustomItemsNotAllowed,
    ItemFull,
    TooManyClaims,
    TooManyCustomItems,
    add_custom_item,
    claim_slot,
    remove_claim,
    save_profile,
    unique_slug,
)


@pytest.fixture
def category(event):
    return Category.objects.create(event=event, name="Sides", allow_custom_items=False)


@pytest.fixture
def attendee(event):
    return Attendee.objects.create(event=event, name="Ana")


# ---------- middleware ----------


def test_attendee_cookie_set_once_and_stable(client, db):
    r1 = client.get("/")
    cookie = r1.cookies["ebs_aid"].value
    assert cookie
    r2 = client.get("/")
    assert "ebs_aid" not in r2.cookies  # not reissued
    assert "ebs_aid" not in Client().get("/health/").cookies  # healthchecks get no cookie


def test_admin_key_unlocks_and_strips_query(client, db):
    r = client.get("/?admin=test-admin-key&x=1")
    assert r.status_code == 302
    assert r["Location"] == "/?x=1"
    assert client.get("/manage/new/").status_code == 200


def test_admin_key_with_plus_survives_query_decoding(client, db, settings):
    settings.ADMIN_KEY = "abc+def/ghi"
    client.get("/?admin=abc+def/ghi")  # pasted unencoded: "+" decodes to a space
    assert client.get("/manage/new/").status_code == 200


def test_wrong_admin_key_ignored(client, db):
    r = client.get("/somewhere/?admin=nope")
    assert r.status_code == 302
    assert r["Location"] == "/somewhere/"
    assert client.get("/manage/new/").status_code == 404


def test_empty_admin_key_setting_disables_admin(client, db, settings):
    settings.ADMIN_KEY = ""
    client.get("/?admin=")
    assert client.get("/manage/new/").status_code == 404


def test_logout_clears_admin(admin_client):
    admin_client.post("/manage/logout/")
    assert admin_client.get("/manage/new/").status_code == 404


def test_rotating_or_clearing_admin_key_revokes_sessions(admin_client, settings):
    assert admin_client.get("/manage/new/").status_code == 200
    settings.ADMIN_KEY = "rotated-key"
    assert admin_client.get("/manage/new/").status_code == 404
    settings.ADMIN_KEY = ""
    assert admin_client.get("/manage/new/").status_code == 404


def test_admin_redirect_cannot_leave_site(client, db):
    r = client.generic("GET", "/", QUERY_STRING="admin=nope", PATH_INFO="//evil.example/")
    assert r.status_code == 302
    assert not r["Location"].startswith("//")
    r = client.generic("GET", "/", QUERY_STRING="admin=nope", PATH_INFO="/a%3Fb/")
    assert "?" not in r["Location"]


def test_manage_routes_404_for_attendees(client, db):
    assert client.get("/manage/new/").status_code == 404


# ---------- slugs ----------


def test_unique_slug(db):
    suffix = "[abcdefghjkmnpqrstuvwxyz23456789]{4}"
    assert re.fullmatch(f"picnic-{suffix}", unique_slug("Picnic!"))
    assert re.fullmatch(f"manage-event-{suffix}", unique_slug("Manage"))
    assert re.fullmatch(f"event-{suffix}", unique_slug("!!!"))
    assert unique_slug("Picnic!") != unique_slug("Picnic!")

    Event.objects.create(title="Picnic", slug="picnic")
    Event.objects.create(title="Picnic", slug="picnic-2")
    assert unique_slug("Picnic!", random_suffix=False) == "picnic-3"
    assert unique_slug("Manage", random_suffix=False) == "manage-event"


# ---------- claims ----------


def test_claim_slot_respects_limit(category, attendee):
    item = Item.objects.create(category=category, name="Chips", slots=2)
    claim_slot(item, attendee)
    claim_slot(item, attendee, note="  salty  ")
    assert item.claims.last().note == "salty"
    with pytest.raises(ItemFull):
        claim_slot(item, attendee)


def test_unlimited_item(category, event):
    item = Item.objects.create(category=category, name="Drinks", slots=None)
    for i in range(25):
        claim_slot(item, Attendee.objects.create(event=event, name=f"v{i}"))
    assert item.claims.count() == 25


def test_claims_per_person_capped_only_on_unlimited_items(category, attendee, settings):
    settings.MAX_CLAIMS_PER_ITEM = 2
    drinks = Item.objects.create(category=category, name="Drinks", slots=None)
    claim_slot(drinks, attendee)
    claim_slot(drinks, attendee)
    with pytest.raises(TooManyClaims):
        claim_slot(drinks, attendee)
    claim_slot(drinks, Attendee.objects.create(event=category.event, name="Bo"))  # others unaffected

    chips = Item.objects.create(category=category, name="Chips", slots=3)
    for _ in range(3):
        claim_slot(chips, attendee)  # limited items are capped by their slots alone
    assert chips.claims.count() == 3


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_never_oversubscribe(tmp_path, settings):
    event = Event.objects.create(title="Race", slug="race")
    category = Category.objects.create(event=event, name="G")
    item = Item.objects.create(category=category, name="Last slot", slots=1)
    attendees = [Attendee.objects.create(event=event, name=f"v{i}") for i in range(8)]
    results = []

    def attempt(v):
        try:
            claim_slot(item, v)
            results.append("ok")
        except ItemFull:
            results.append("full")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(v,)) for v in attendees]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert Claim.objects.filter(item=item).count() == 1
    assert results.count("ok") == 1


def test_custom_item_lifecycle(category, attendee):
    with pytest.raises(CustomItemsNotAllowed):
        add_custom_item(category, attendee, "Pie")
    category.allow_custom_items = True
    category.save()
    item = add_custom_item(category, attendee, " Pie ", note="apple")
    assert item.is_custom and item.name == "Pie" and item.claims.count() == 1
    assert remove_claim(item.claims.get()) is None
    assert not Item.objects.filter(pk=item.pk).exists()


def test_custom_items_per_person_capped(category, attendee, settings):
    settings.MAX_CUSTOM_ITEMS_PER_ATTENDEE = 2
    category.allow_custom_items = True
    category.custom_item_limit = None
    category.save()
    add_custom_item(category, attendee, "Pie")
    add_custom_item(category, attendee, "Cake")
    with pytest.raises(TooManyCustomItems):
        add_custom_item(category, attendee, "Cookies")
    add_custom_item(category, Attendee.objects.create(event=category.event, name="Bo"), "Cookies")
    assert category.items.filter(is_custom=True).count() == 3


def test_remove_claim_keeps_regular_item(category, attendee):
    item = Item.objects.create(category=category, name="Salad", slots=1)
    claim = claim_slot(item, attendee)
    assert remove_claim(claim) == item
    assert Item.objects.filter(pk=item.pk).exists()


# ---------- profile form ----------


def test_profile_form_custom_fields(event):
    phone = CustomField.objects.create(event=event, label="Phone", field_type="phone", required=True)
    guest = CustomField.objects.create(event=event, label="Guest", is_public=True)
    vegan = CustomField.objects.create(event=event, label="Vegan?", field_type="checkbox")

    form = build_profile_form(event, data={"name": "Bo"})
    assert not form.is_valid()
    assert phone.form_key in form.errors

    form = build_profile_form(
        event, data={"name": "Bo", phone.form_key: "555-123-4567", guest.form_key: "Cy", vegan.form_key: "on"}
    )
    assert form.is_valid(), form.errors
    v = save_profile(event, uuid.uuid4(), form.cleaned_data["name"], form.field_values())
    stored = {fv.field.label: fv.value for fv in v.values.all()}
    assert stored == {"Phone": "555-123-4567", "Guest": "Cy", "Vegan?": "1"}
    assert [fv.field.label for fv in v.public_values()] == ["Guest"]

    # Editing pre-fills from existing values.
    edit = build_profile_form(event, attendee=v)
    assert edit.initial["name"] == "Bo" and edit.initial[vegan.form_key] is True

    # An optional yes/no stays a single checkbox, and leaving it unticked is fine.
    form = build_profile_form(event, data={"name": "Bo", phone.form_key: "555-123-4567"})
    assert form.is_valid(), form.errors
    assert form.field_values()[vegan] == "0"


def test_required_yes_no_field_accepts_yes_and_no(event):
    drive = CustomField.objects.create(event=event, label="Can you drive?", field_type="checkbox", required=True)
    form = build_profile_form(event, data={"name": "Bo"})
    assert not form.is_valid() and drive.form_key in form.errors
    assert 'type="radio"' in str(form[drive.form_key])

    for answer, stored in [("True", "1"), ("False", "0")]:
        form = build_profile_form(event, data={"name": "Bo", drive.form_key: answer})
        assert form.is_valid(), form.errors
        assert form.field_values()[drive] == stored

    # Editing pre-selects the stored answer, including "No".
    attendee = save_profile(event, uuid.uuid4(), "Bo", {drive: "0"})
    html = str(build_profile_form(event, attendee=attendee)[drive.form_key])
    assert re.search(r'value="False"[^>]*checked', html) and not re.search(r'value="True"[^>]*checked', html)


@pytest.mark.parametrize(
    "value, ok",
    [
        ("555-123-4567", True),
        ("(555) 123 4567", True),
        ("+44 20 7946 0958", True),
        ("555.123.4567", True),
        ("call me", False),
        ("-------", False),
        ("12345", False),
        ("1234567890123456", False),
    ],
)
def test_phone_field_light_validation(event, value, ok):
    phone = CustomField.objects.create(event=event, label="Phone", field_type="phone", required=True)
    form = build_profile_form(event, data={"name": "Bo", phone.form_key: value})
    assert form.is_valid() is ok
    if not ok:
        assert form.errors[phone.form_key] == ["Enter a phone number, like 555-123-4567."]


@pytest.mark.parametrize("value, ok", [("bo@example.com", True), ("bo@example", False), ("not an email", False)])
def test_email_field_light_validation(event, value, ok):
    email = CustomField.objects.create(event=event, label="Email", field_type="email", required=True)
    form = build_profile_form(event, data={"name": "Bo", email.form_key: value})
    assert form.is_valid() is ok
    if not ok:
        assert form.errors[email.form_key] == ["Enter an email address, like name@example.com."]


def test_stored_secret_is_generated_once_and_private(tmp_path):
    from config.keys import stored_secret

    path = tmp_path / ".admin-key"
    first, created = stored_secret(path)
    again, created_again = stored_secret(path)
    assert created and not created_again
    assert first == again and len(first) >= 40
    assert path.stat().st_mode & 0o777 == 0o600
