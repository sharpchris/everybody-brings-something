"""Site settings page and how its values show up across the site."""

import datetime

import pytest
from django.urls import reverse

from events.models import Event, SiteSettings

URL = reverse("manage_site_settings")


def _post(client, **overrides):
    data = {"organization": "", "time_zone": "America/Chicago", "home_message": "", "contact_email": ""}
    data.update(overrides)
    return client.post(URL, data)


def test_site_settings_admin_only(client, db):
    assert client.get(URL).status_code == 404
    assert _post(client, organization="Hacked").status_code == 404
    assert SiteSettings.load().organization == ""


def test_site_settings_save(admin_client):
    page = admin_client.get(URL)
    assert '<optgroup label="Common">' in page.content.decode()

    response = _post(
        admin_client, organization="Riverside PTA", time_zone="America/Denver",
        home_message="Hi", contact_email="organizer@example.com",
    )
    assert response.status_code == 302 and response.url == URL
    site = SiteSettings.load()
    assert (site.organization, site.time_zone, site.contact_email) == (
        "Riverside PTA", "America/Denver", "organizer@example.com",
    )
    assert "Site settings saved." in admin_client.get(URL).content.decode()


def test_invalid_time_zone_rejected(admin_client):
    response = _post(admin_client, time_zone="Mars/Olympus_Mons", organization="Riverside PTA")
    assert response.status_code == 200
    assert "a known time zone" in response.content.decode()
    site = SiteSettings.load()
    assert site.time_zone != "Mars/Olympus_Mons" and site.organization == ""


def test_organization_in_header_and_title(client, event):
    SiteSettings.objects.update_or_create(pk=1, defaults={"organization": "Riverside <PTA>"})
    body = client.get(event.get_absolute_url()).content.decode()
    assert "<title>Summer Potluck · Everybody Brings Something – Riverside &lt;PTA&gt;</title>" in body
    assert '<span class="org">– Riverside &lt;PTA&gt;</span>' in body


@pytest.mark.parametrize("tz, hour", [("America/New_York", "8 PM"), ("America/Los_Angeles", "5 PM")])
def test_event_time_uses_site_time_zone(client, db, tz, hour):
    starts = datetime.datetime(2030, 6, 15, 0, 0, tzinfo=datetime.UTC)
    event = Event.objects.create(title="Picnic", slug="picnic", starts_at=starts)
    SiteSettings.objects.update_or_create(pk=1, defaults={"time_zone": tz})
    body = client.get(event.get_absolute_url()).content.decode()
    assert hour in body


def test_event_with_same_start_and_end_shows_one_time(client, db):
    at = datetime.datetime(2030, 6, 15, 22, 0, tzinfo=datetime.UTC)
    event = Event.objects.create(title="Picnic", slug="picnic", starts_at=at, ends_at=at)
    body = client.get(event.get_absolute_url()).content.decode()
    assert "Saturday, June 15, 2030 · 6 PM" in body and "6–6" not in body


def test_home_message_replaces_default_for_attendees(client, db):
    SiteSettings.objects.update_or_create(pk=1, defaults={"home_message": "Ask the front office.\n\n<b>Thanks</b>"})
    body = client.get("/").content.decode()
    assert "<p>Ask the front office.</p>" in body and "&lt;b&gt;Thanks&lt;/b&gt;" in body
    assert "open the event link" not in body


def test_contact_footer(client, db, settings):
    settings.DEBUG = False  # so the 404 uses our template
    settings.ALLOWED_HOSTS = ["testserver"]
    assert "site-footer" not in client.get("/").content.decode()
    SiteSettings.objects.update_or_create(pk=1, defaults={"contact_email": "help@example.com"})
    for path in ("/", "/no-such-event/"):
        body = client.get(path).content.decode()
        assert '<a href="mailto:help@example.com">help@example.com</a>' in body
