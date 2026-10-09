"""Full flow: admin builds an event, two attendees sign up, privacy and ownership hold, admin edits."""

import re

from playwright.sync_api import expect


def _accept_dialogs(page):
    page.on("dialog", lambda d: d.accept())


def _item(page, name):
    return page.locator(".sheet-item").filter(has=page.locator(".item-name", has_text=name))


def test_potluck_end_to_end(admin_page, attendee_page_factory, live_server, db):
    admin = admin_page
    _accept_dialogs(admin)

    # --- Admin creates the event; the slug is the title plus a short random suffix.
    admin.goto("/manage/new/")
    admin.get_by_label("Title").fill("Fall Potluck 2026")
    admin.get_by_label("Location").fill("Riverside Park")
    admin.get_by_role("button", name=re.compile("Create", re.I)).click()
    expect(admin).to_have_url(re.compile(r"/fall-potluck-2026-[a-z2-9]{4}/$"))
    slug = admin.url.rstrip("/").rsplit("/", 1)[1]

    # --- Custom fields: a private phone (required) and a public guest name.
    admin.goto(f"/manage/{slug}/settings/")
    add_field = admin.locator("#fields form").last
    add_field.get_by_label("Label").fill("Phone")
    add_field.get_by_label("Field type").select_option("phone")
    add_field.get_by_label("Required").check()
    add_field.get_by_role("button", name="Add field").click()
    expect(admin.locator("#field-1, #fields article").first).to_contain_text("Phone")

    add_field = admin.locator("#fields form").last
    add_field.get_by_label("Label").fill("Guest")
    add_field.get_by_label("Visible to other attendees").check()
    add_field.get_by_role("button", name="Add field").click()
    expect(admin.locator("#fields article")).to_have_count(2)

    # --- Categories and items, inline on the sheet.
    admin.goto(f"/{slug}/")
    admin.locator("#newcategory_name").fill("Sides")
    admin.get_by_role("button", name="Add category").click()
    sides = admin.locator(".sheet-category").filter(has_text="Sides")
    expect(sides).to_be_visible()

    sides.get_by_role("button", name="Add suggested item to Sides").click()
    form = admin.locator("form[id^=item-form-new]")
    form.get_by_label("Name").fill("Chips")
    form.get_by_label("Signups allowed").fill("1")
    form.get_by_role("button").first.click()
    expect(_item(admin, "Chips")).to_contain_text("0 of 1 signed up")

    sides = admin.locator(".sheet-category").filter(has_text="Sides")
    sides.get_by_role("button", name="Add suggested item to Sides").click()
    form = admin.locator("form[id^=item-form-new]")
    form.get_by_label("Name").fill("Drinks")
    form.get_by_label("Unlimited signups").check()
    form.get_by_role("button").first.click()
    expect(_item(admin, "Drinks")).to_contain_text("Unlimited")

    admin.get_by_role("switch", name="Attendees can add items to Sides").check()
    expect(admin.get_by_role("button", name="Bring something else to Sides")).to_be_visible()

    # --- Attendee 1 signs up for Chips: profile form appears first.
    v1 = attendee_page_factory()
    _accept_dialogs(v1)
    v1.goto(f"/{slug}/")
    _item(v1, "Chips").get_by_role("button", name="I'll bring Chips").click()
    chips = _item(v1, "Chips")
    chips.get_by_label("Your name").fill("Ana")
    chips.get_by_role("button", name="I'll bring this").click()
    # Required field: the browser blocks submit (server-side check is covered by unit tests).
    assert chips.get_by_label("Phone").evaluate("el => !el.checkValidity()")
    chips.get_by_label("Phone").fill("555-201-9988")
    chips.get_by_label("Guest").fill("Bea")
    chips.get_by_role("button", name="I'll bring this").click()
    expect(_item(v1, "Chips").locator(".slot.mine .signer")).to_have_text("Ana")
    expect(v1.locator("#my-info")).to_contain_text("555-201-9988")  # own private data in own panel

    # One tap for a second item now that the profile exists.
    _item(v1, "Drinks").get_by_role("button", name="I'll bring Drinks").click()
    expect(_item(v1, "Drinks").locator(".signer")).to_have_text("Ana")
    expect(_item(v1, "Drinks").get_by_role("button", name="I'll bring another Drinks")).to_be_visible()

    # Add a note.
    _item(v1, "Drinks").get_by_role("link", name="Add note").click()
    _item(v1, "Drinks").locator("input[name=note]").fill("lemonade")
    _item(v1, "Drinks").get_by_role("button", name="Save note").click()
    expect(_item(v1, "Drinks")).to_contain_text("lemonade")

    # --- Attendee 2 sees the name and public field, never the private phone.
    v2 = attendee_page_factory()
    _accept_dialogs(v2)
    v2.goto(f"/{slug}/")
    chips2 = _item(v2, "Chips")
    expect(chips2.locator(".signer")).to_have_text("Ana")
    expect(chips2).to_contain_text("Bea")
    assert "555-201-9988" not in v2.content()
    expect(chips2.get_by_role("button", name=re.compile("Remove"))).to_have_count(0)
    expect(chips2.locator(".slot-claim")).to_have_count(0)  # full
    expect(chips2.locator(".badge.full")).to_be_visible()

    # Attendee 2 adds a custom item, profile in the same step.
    v2.get_by_role("button", name="Bring something else to Sides").click()
    category = v2.locator(".sheet-category").filter(has_text="Sides")
    category.get_by_label("What are you bringing?").fill("Deviled eggs")
    category.get_by_label("Your name").fill("Cy")
    category.get_by_label("Phone").fill("555-777-0000")
    category.get_by_role("button", name="Add it").click()
    expect(_item(v2, "Deviled eggs").locator(".signer")).to_have_text("Cy")

    # --- Attendee 1 edits their name; it updates on the sheet.
    v1.reload()
    v1.locator("#my-info").get_by_role("button", name=re.compile("Edit my info")).or_(
        v1.locator("#my-info").get_by_role("link", name=re.compile("Edit my info"))
    ).first.click()
    v1.locator("#my-info").get_by_label("Your name").fill("Ana Lee")
    v1.locator("#my-info").get_by_role("button", name=re.compile("Save")).click()
    expect(_item(v1, "Chips").locator(".signer")).to_have_text("Ana Lee")

    # --- Admin sees private data in responses and can remove anyone.
    admin.goto(f"/manage/{slug}/responses/")
    expect(admin.locator("#responses")).to_contain_text("555-201-9988")
    expect(admin.locator("#responses")).to_contain_text("555-777-0000")

    admin.goto(f"/{slug}/")
    _item(admin, "Deviled eggs").get_by_role("button", name="Remove").click()
    expect(_item(admin, "Deviled eggs")).to_have_count(0)  # custom item gone with its last claim

    # Attendee 1 removes their own Chips claim, freeing the slot.
    v1.reload()
    _item(v1, "Chips").get_by_role("button", name="Remove me").click()
    expect(_item(v1, "Chips")).to_contain_text("0 of 1 signed up")
