import os

os.environ.setdefault("DEBUG", "1")

from .settings import *  # noqa: E402,F403

# A file-backed test DB so concurrency tests exercise real SQLite locking.
# Every test client shares 127.0.0.1; rate-limit tests lower this themselves.
NEW_ATTENDEES_PER_HOUR = 10_000

DATABASES["default"]["TEST"] = {"NAME": BASE_DIR / "test_db.sqlite3"}  # noqa: F405
