"""Smoke tests: the health endpoint and the ?admin= key flow."""

import re

from playwright.sync_api import expect

from .conftest import ADMIN_KEY


def test_health_endpoint(page, live_server):
    response = page.request.get(f"{live_server.url}/health/")
    assert response.status == 200
    assert response.json() == {"status": "ok"}


def test_admin_key_is_stripped_and_unlocks_admin_mode(admin_page, live_server):
    assert "admin=" not in admin_page.url
    expect(admin_page).to_have_url(re.compile(rf"^{re.escape(live_server.url)}/?$"))
    expect(admin_page.locator(".admin-bar")).to_contain_text("Admin mode")


def test_admin_key_strip_keeps_other_query_params(attendee_page_factory):
    page = attendee_page_factory()
    page.goto(f"/?foo=bar&admin={ADMIN_KEY}")
    assert "admin=" not in page.url
    assert "foo=bar" in page.url
    expect(page.locator(".admin-bar")).to_be_visible()


def test_wrong_admin_key_does_not_unlock(attendee_page_factory):
    page = attendee_page_factory()
    page.goto("/?admin=wrong-key")
    assert "admin=" not in page.url
    expect(page.locator(".admin-bar")).to_have_count(0)


def test_admin_mode_is_per_browser(admin_page, attendee_page_factory):
    attendee = attendee_page_factory()
    attendee.goto("/")
    expect(admin_page.locator(".admin-bar")).to_be_visible()
    expect(attendee.locator(".admin-bar")).to_have_count(0)
