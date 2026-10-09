"""Shared fixtures for the unit and view tests."""

import pytest

ADMIN_KEY = "test-admin-key"


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.ADMIN_KEY = ADMIN_KEY
    settings.DEBUG = True


@pytest.fixture
def admin_client(client, db):
    """A test client with admin mode unlocked via the query-string key."""
    client.get(f"/?admin={ADMIN_KEY}")
    return client


@pytest.fixture
def event(db):
    from events.models import Event

    return Event.objects.create(title="Summer Potluck", slug="summer-potluck")
