"""Generate-once secrets kept next to the database, so a fresh install needs no hand-made keys."""

import os
import secrets
from pathlib import Path


def stored_secret(path: Path) -> tuple[str, bool]:
    """Return the secret saved at `path`, creating a random one the first time.

    The second value is True only for the call that created it. Creation is atomic
    (O_EXCL), so concurrent processes all end up with the same value.
    """
    try:
        return path.read_text().strip(), False
    except FileNotFoundError:
        pass
    value = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip(), False
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    return value, True
