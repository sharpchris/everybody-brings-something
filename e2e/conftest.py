"""Playwright e2e fixtures: a live Django server plus isolated browser contexts.

Run with `uv run pytest e2e` (needs `uv run playwright install chromium` once).
"""

import os

import pytest

# Playwright's sync API runs an event loop in the test thread; Django refuses
# ORM calls from a thread with a running loop unless this is set.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

ADMIN_KEY = "test-admin-key"


def pytest_collection_modifyitems(items):
    for item in items:
        if "e2e" in item.path.parts:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.ADMIN_KEY = ADMIN_KEY
    # Plain-HTTP live server: keep cookies non-Secure, as in local dev.
    settings.DEBUG = True


@pytest.fixture(scope="session")
def base_url(live_server):
    """Overrides pytest-base-url so `page.goto("/path")` targets the live server."""
    return live_server.url


@pytest.fixture
def attendee_page_factory(browser, live_server):
    """Returns a function that opens a fresh browser context (own cookies = own attendee)."""
    contexts = []

    def make_page():
        context = browser.new_context(base_url=live_server.url)
        contexts.append(context)
        return context.new_page()

    yield make_page
    for context in contexts:
        context.close()


@pytest.fixture
def admin_page(attendee_page_factory, live_server):
    """A page whose context has unlocked admin mode via the query-string key."""
    page = attendee_page_factory()
    page.goto(f"/?admin={ADMIN_KEY}")
    return page
