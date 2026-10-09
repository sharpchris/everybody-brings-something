# Contributing

Thanks for helping out. Bug reports, fixes and small focused features are all welcome. For anything larger, open an issue first so we can agree on the approach before you spend time on it.

## Setup

You need [uv](https://docs.astral.sh/uv/). Python 3.13 is pinned in `.python-version` and uv installs it for you.

```sh
uv sync
DEBUG=1 ADMIN_KEY=dev uv run python manage.py migrate
DEBUG=1 ADMIN_KEY=dev uv run python manage.py runserver
```

Open http://localhost:8000/?admin=dev to unlock admin mode.

## Tests

```sh
uv run pytest                        # unit and view tests
uv run playwright install chromium   # once
uv run pytest e2e                    # browser tests
```

CI runs both on every push and pull request. Please make sure they pass before you open a PR.

Keep tests lean: cover behaviour that could realistically break (permissions, slot limits, form validation, the main user flows), not framework features or trivial code. One good test beats five near-duplicates.

## Style

- Keep it simple. This is a small app meant to be easy to self-host and easy to read. Prefer plain Django, server-rendered templates and htmx over new dependencies or JavaScript.
- No build step. Frontend libraries are vendored under `static/vendor/`; if you add one, record its version and license in `THIRD_PARTY_NOTICES.md`.
- Configuration comes from environment variables (see `config/settings.py`). Document any new variable in the README and `.env.example`.
- Write migrations for model changes (`uv run python manage.py makemigrations`) and commit them.
- UI text uses sentence case and plain language.

## Pull requests

- One topic per PR, with a short description of what changed and why.
- Include screenshots for visible UI changes.
- By contributing, you agree your work is licensed under the project's MIT license.

Security issues: please don't open a public issue, see [SECURITY.md](SECURITY.md).
