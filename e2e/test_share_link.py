"""The share link follows the title until it's edited by hand."""

import re

from playwright.sync_api import expect

SUFFIX = "[abcdefghjkmnpqrstuvwxyz23456789]{4}"


def test_share_link_follows_title_until_edited(admin_page):
    page = admin_page
    page.goto("/manage/new/")
    title, link = page.get_by_label("Title"), page.get_by_label("Share link")

    title.fill("Café Brunch & Games!")
    expect(link).to_have_value(re.compile(f"^cafe-brunch-games-{SUFFIX}$"))
    suffix = link.input_value()[-4:]
    title.fill("Brunch")
    expect(link).to_have_value(f"brunch-{suffix}")  # one suffix per page load
    title.fill("")
    expect(link).to_have_value("")

    link.fill("brunch")
    title.fill("Something else entirely")
    expect(link).to_have_value("brunch")  # hand-edited: no longer overwritten

    # Backspacing the link to empty while editing must not bring auto-fill back.
    link.click()
    for _ in range(len("brunch")):
        link.press("Backspace")
    expect(link).to_have_value("")
    title.fill("Still not auto")
    expect(link).to_have_value("")
    link.press_sequentially("my-link")
    expect(link).to_have_value("my-link")


def test_typing_in_link_first_stops_auto_fill(admin_page):
    page = admin_page
    page.goto("/manage/new/")
    title, link = page.get_by_label("Title"), page.get_by_label("Share link")
    title.fill("Picnic")
    expect(link).to_have_value(re.compile(f"^picnic-{SUFFIX}$"))
    auto = link.input_value()
    link.evaluate("el => { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }")
    link.press("Backspace")  # a single keystroke counts as a manual edit
    title.fill("Picnic at the lake")
    expect(link).to_have_value(auto[:-1])


def test_manual_link_survives_validation_error(admin_page, db):
    from events.models import Event

    Event.objects.create(title="Taken", slug="taken")
    page = admin_page
    page.goto("/manage/new/")
    page.get_by_label("Title").fill("Taken")
    page.get_by_label("Share link").fill("taken")  # hand-typed and already used
    page.get_by_role("button", name="Create event").click()
    link = page.get_by_label("Share link")
    expect(link).to_have_value("taken")
    page.get_by_label("Title").fill("Taken again")
    expect(link).to_have_value("taken")  # still manual after the re-render


def test_settings_share_link_does_not_follow_title(admin_page, db):
    from events.models import Event

    Event.objects.create(title="Picnic", slug="picnic")
    page = admin_page
    page.goto("/manage/picnic/settings/")
    page.get_by_label("Title").fill("Picnic in the park")
    expect(page.get_by_label("Share link")).to_have_value("picnic")
