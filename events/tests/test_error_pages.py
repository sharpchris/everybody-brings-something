import pytest
from django.test import Client, RequestFactory
from django.views.defaults import server_error

from events.models import Attendee, Category, Item
from events.services import claim_slot


@pytest.fixture
def prod(settings):
    """Error templates are only used with DEBUG off."""
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver"]


def test_404_page_for_unknown_event(client, db, prod):
    r = client.get("/no-such-event/")
    assert r.status_code == 404
    body = r.content.decode()
    assert "We couldn't find that page" in body
    assert "Go to the home page" in body
    assert "app.css" in body  # uses the site layout


def test_404_for_admin_links_to_events(db, admin_client, prod):
    r = admin_client.get("/no-such-event/")
    assert r.status_code == 404
    assert "See all events" in r.content.decode()


def test_admin_routes_404_page_for_non_admins(client, db, prod):
    r = client.get("/manage/new/")
    assert r.status_code == 404
    assert "We couldn't find that page" in r.content.decode()


def test_403_page_when_editing_someone_elses_claim(client, event, prod):
    category = Category.objects.create(event=event, name="Sides")
    item = Item.objects.create(category=category, name="Chips", slots=1)
    owner = Attendee.objects.create(event=event, name="Ana")
    claim = claim_slot(item, owner)

    r = Client().post(f"/{event.slug}/claims/{claim.pk}/delete/")
    assert r.status_code == 403
    assert "You can't change that signup" in r.content.decode()


def test_500_page_is_self_contained(prod):
    r = server_error(RequestFactory().get("/"))
    assert r.status_code == 500
    body = r.content.decode()
    assert "Something went wrong on our end" in body
    assert "<style>" in body and "/static/" not in body
