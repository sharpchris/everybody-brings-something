# Everybody Brings Something

A self-hosted signup sheet for potlucks and outings. An organizer creates an event with categories of suggested items (Mains, Sides, Desserts…), slot limits and optional questions. Attendees sign up by name with no accounts, and can edit or remove their own entries later.

It runs as one small container with a SQLite database: Django 5.2, htmx 2 and Pico CSS 2 (vendored, no build step), WhiteNoise and gunicorn.

<!-- Screenshot: add docs/screenshot.png and uncomment.
![An event signup sheet](docs/screenshot.png)
-->

## What it does

**For the organizer** (admin mode):

- Create an event with a date, location and description. Its share link fills in from the title as you type, with a short random ending (like `summer-potluck-k3f9`) so it can't be guessed, and you can change it.
- Copy the event's share link with one click, and use **Guest view** to see the page exactly as attendees do.
- Group suggested items into categories (Mains, Sides, Desserts…). Each item takes a set number of signups, or unlimited.
- Let attendees add their own items to a category, up to a cap (on by default, 10) or with no limit.
- Ask for extra details with custom fields: text, phone, email or yes/no. Add them while creating the event or later under Event settings. Each can be required or optional, and is private unless you make it visible next to people's names. A required yes/no question accepts either answer.
- Answers stay safe when you change your mind: making a private field public asks you to confirm first, since earlier answers would become visible, and a field's type is locked once people have answered.
- Edit and reorder categories and items right on the sheet with the icon controls.
- See everyone's answers, private ones included, on the Responses page, and edit or remove any signup.
- Name your group, set the time zone, add a home page message and a contact email under [Site settings](#site-settings).

**For attendees:**

- No account. Open the share link and tap a blank "I'll bring this" line to sign up. Your name and the organizer's questions are asked once per event.
- Add an optional note, like "gluten-free" or "bringing the big pot".
- Use "+ Bring something else" to write in an item that isn't listed.
- Come back later in the same browser to edit your info or remove yourself.
- Private answers are only ever shown to the organizer.

## Quick start

You need Docker with the Compose plugin.

```sh
mkdir everybody-brings-something && cd everybody-brings-something
curl -fsSLO https://raw.githubusercontent.com/sharpchris/everybody-brings-something/main/compose.yaml
curl -fsSL -o .env https://raw.githubusercontent.com/sharpchris/everybody-brings-something/main/.env.example
```

In `.env`, set `SITE_URL` to the address people will use, such as `https://signup.example.org` or `http://192.168.1.20:8000`. Leave it empty to try it out on `http://localhost:8000`.

Then start it and get your admin link:

```sh
docker compose up -d
docker compose exec web python manage.py admin_link
```

Open that link to unlock admin mode and create your first event. On first start the app generates a random admin key and secret key and keeps them in the `data` volume with the database, so they survive restarts and upgrades; the admin link is also printed once in `docker compose logs`. Migrations run automatically on every start.

Running the image without compose? Mount a volume at `/data`, or the database is lost when the container is removed:

```sh
docker run -d -p 8000:8000 --env-file .env -v ebs-data:/data ghcr.io/sharpchris/everybody-brings-something:latest
```

## Configuration

All settings are environment variables, read from `.env` by `docker compose`.

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | generated | Signs sessions and attendee cookies. If unset, a random one is generated on first start and kept in `/data/.secret-key`. Changing it signs everyone out. |
| `ADMIN_KEY` | generated | The `?admin=` key. If unset, a random one is generated on first start and kept in `/data/.admin-key` (`manage.py admin_link` prints the link). If you set your own: at least 20 URL-safe characters (e.g. `openssl rand -hex 32`). `off` disables admin mode. |
| `SITE_URL` | empty | The public address, e.g. `https://signup.example.org`. Sets the allowed host, the trusted CSRF origin and the `HTTPS` default. |
| `HTTPS` | on if `SITE_URL` (or a `CSRF_TRUSTED_ORIGINS` entry) is `https://`, or `BEHIND_PROXY` is on | HTTPS-only cookies, plus HSTS on requests the app knows are HTTPS (needs `BEHIND_PROXY`). Set `0` for plain HTTP, `1` to force on. |
| `BEHIND_PROXY` | `0` (`1` on Railway) | Trust `X-Forwarded-Proto` from a reverse proxy that terminates TLS. Only enable when the app is reachable solely through the proxy. |
| `SECURE_SSL_REDIRECT` | `0` | Redirect HTTP to HTTPS in the app. Only takes effect with `HTTPS` and `BEHIND_PROXY` both on (otherwise it would loop). Usually the proxy does this. `/health/` is never redirected. |
| `SECURE_HSTS_SECONDS` | `2592000` (30 days) | HSTS max-age when `HTTPS` is on. No subdomains or preload, so a domain change stays reversible. |
| `ALLOWED_HOSTS` | empty | Extra hostnames, comma-separated. `localhost` and `127.0.0.1` are always allowed. |
| `CSRF_TRUSTED_ORIGINS` | empty | Extra origins (`https://…`), comma-separated, if the site answers on more than `SITE_URL`. |
| `TIME_ZONE` | `America/New_York` | Time zone for new installs. Change the live one under Site settings. |
| `LOG_LEVEL` | `INFO` | Logs go to stdout (`docker compose logs`). |
| `WEB_CONCURRENCY` | `2` | gunicorn worker processes (4 threads each). |
| `PORT` | `8000` | Port gunicorn listens on inside the container. |
| `DATABASE_PATH` | `/data/db.sqlite3` in Docker, `./db.sqlite3` otherwise | SQLite file. Its directory must exist or startup fails. |
| `DEBUG` | `0` | `1` only for local development. Never in production. |
| `MAX_CLAIMS_PER_ITEM` | `5` | Signups one person can make on a single unlimited item. Items with a slot count are limited by their slots. |
| `MAX_CUSTOM_ITEMS_PER_ATTENDEE` | `3` | Items one person can add to a category with "+ Bring something else". |
| `NEW_ATTENDEES_PER_HOUR` | `30` | New attendee profiles allowed per client IP per hour. Counted per gunicorn worker, so it's a light brake, not an exact limit. Behind a proxy (`BEHIND_PROXY=1`) the IP comes from `X-Forwarded-For`, which the proxy must set. |

Boolean variables accept `1`/`true`/`yes`/`on` (anything else is off). An empty value such as `HTTPS=` means "use the default".

## HTTPS and reverse proxies

The container serves plain HTTP on port 8000. For a public site, put a reverse proxy in front that handles TLS certificates and forwards to it, then set:

```sh
SITE_URL=https://signup.example.org
BEHIND_PROXY=1
```

The proxy must send `X-Forwarded-Proto` (Caddy, Traefik and most nginx configs do) and should redirect HTTP to HTTPS. Publish the container's port only to the proxy, for example `"127.0.0.1:8000:8000"` in `compose.yaml`, so nobody can bypass it. A minimal Caddyfile, with automatic certificates:

```
signup.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

With nginx, use `proxy_pass http://127.0.0.1:8000;` plus `proxy_set_header Host $host;` and `proxy_set_header X-Forwarded-Proto $scheme;`. With Traefik, route to the `web` service on port 8000.

**Plain HTTP on a home network.** Set `SITE_URL=http://192.168.1.20:8000` (your server's address), or leave it empty and use `localhost`. `HTTPS` then stays off, so cookies work without TLS. Don't expose a plain-HTTP install to the internet.

## Site settings

In admin mode, open **Site settings** (`/manage/site/`) to set:

- **Organization**: shown after the site name, e.g. "Everybody Brings Something – Riverside PTA".
- **Time zone**: used to show event dates and times. Starts as `TIME_ZONE`.
- **Home page message**: shown on the home page to people who don't have an event link.
- **Contact email**: shown at the bottom of every page.

These are stored in the database, so they survive upgrades and restarts.

## How admin mode works

- There are no accounts. Visiting any page with `?admin=<ADMIN_KEY>` sets a flag in a signed session cookie (30 days), then redirects to the same URL with the key removed so it doesn't linger in history or get shared.
- A wrong key is silently ignored. `ADMIN_KEY=off` disables admin mode entirely.
- Lost the link? `docker compose exec web python manage.py admin_link` prints it.
- While unlocked, an "Admin mode" bar shows at the top with a "Leave admin mode" button.
- **Guest view** (button on each event page) switches admin mode off for that browser until you click "Exit guest view", with a colored frame so you can't miss it. You're still logged in as admin underneath. Signups you make in guest view are real, recorded as your browser's own attendee.
- Admin sessions are tied to the current key: changing it logs every admin out immediately. To rotate a generated key, delete `/data/.admin-key` and restart (a new one is generated and printed), or set `ADMIN_KEY` yourself.
- "Leave admin mode" signs out that browser only; a copy of its cookie would stay valid until it expires. If a device with admin mode is lost or shared, rotate `ADMIN_KEY`.
- gunicorn's access log omits query strings, so the key isn't written there. A reverse proxy or hosting platform may still log the URL you first visit, so treat the key like a password and rotate it if logs are shared.
- When `DEBUG` is off, a non-empty `ADMIN_KEY` must be at least 20 characters (the app refuses to start otherwise).

## How attendees are identified

- Every browser gets a signed `ebs_aid` cookie holding a random UUID (2 years, HttpOnly, SameSite=Lax, Secure when `HTTPS` is on).
- An attendee's per-event profile (name and custom fields) and claims are tied to that UUID, so only that browser can edit them.
- Clearing cookies or switching devices means the attendee can no longer edit their old signups. An admin can still edit or delete anything.

## Backups

Everything is in one SQLite database in the `data` volume. SQLite runs in WAL mode, so a plain file copy of a busy database can miss recent writes. Use SQLite's online backup, which is safe while the app runs:

```sh
docker compose exec web python -c "import sqlite3; s=sqlite3.connect('/data/db.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d); d.close()"
docker compose cp web:/data/backup.sqlite3 ./backup-$(date +%F).sqlite3
docker compose exec web rm /data/backup.sqlite3
```

Or stop the app first and copy the file directly:

```sh
docker compose stop web
docker compose cp web:/data/db.sqlite3 ./backup.sqlite3
docker compose start web
```

To restore, copy the backup into the volume and load it with SQLite's backup API (this keeps the database owned by the app user and handles the WAL files):

```sh
docker compose stop web
docker compose cp ./backup.sqlite3 web:/data/restore.sqlite3
docker compose run --rm --no-deps --entrypoint python web -c "import os, sqlite3; s=sqlite3.connect('/data/restore.sqlite3'); d=sqlite3.connect('/data/db.sqlite3'); s.backup(d); d.close(); s.close(); os.remove('/data/restore.sqlite3')"
docker compose start web
```

## Upgrading

```sh
docker compose pull
docker compose up -d
```

Migrations run automatically when the container starts. Take a backup first.

`latest` follows the main branch (published only after the tests pass). To stay on a release instead, pin a version tag such as `ghcr.io/sharpchris/everybody-brings-something:0.1` with `EBS_IMAGE` in your shell or `.env`.

## Deploy on Railway

`railway.json` builds the Dockerfile, checks `/health/`, runs 1 replica and requires a volume at `/data`.

1. Create a service from this GitHub repo.
2. Add a volume yourself; the repo can't create one. In the project canvas, right-click the service (or press `⌘K` / `Ctrl+K`), choose **Attach volume**, and set the mount path to `/data`. The database lives at `/data/db.sqlite3`, so this volume is what keeps your events across deploys and restarts. Without it the deploy won't start (`railway.json` requires the mount), and without that check everything would be wiped on every deploy. Railway mounts volumes as root; the container fixes the ownership on startup, so no extra setting is needed.
3. Set `SECRET_KEY` and `ADMIN_KEY` under Variables (recommended on Railway). That keeps the keys in the dashboard, where you can copy or change them; changing `ADMIN_KEY` redeploys and logs every admin out. Generate each value with `openssl rand -hex 32` and paste it in. If you turn this project into a [Railway template](https://docs.railway.com/templates/create#template-variable-functions), use `${{secret(64, "abcdef0123456789")}}` as the value so each deploy gets its own key (letters and digits only, so it's safe in the admin link). Leave `DEBUG` unset.

   Variables always win. If you skip this step, random keys are generated into the volume on the first deploy instead, the admin link appears once in the deploy logs, and `python manage.py admin_link` in the service's shell (`railway ssh`) shows it again.
4. Generate a domain under Settings → Networking. `SITE_URL` defaults to `https://$RAILWAY_PUBLIC_DOMAIN` and `BEHIND_PROXY` defaults on. For a custom domain, set `SITE_URL` to it.
5. Keep the service at 1 replica (SQLite on a volume can't be shared) and turn on backups in the volume's settings.

Expect a few seconds of downtime per deploy, because Railway stops the old container before mounting the volume on the new one.

## Local development

Requires [uv](https://docs.astral.sh/uv/). Python 3.13 is pinned in `.python-version`.

```sh
uv sync
DEBUG=1 ADMIN_KEY=dev uv run python manage.py migrate
DEBUG=1 ADMIN_KEY=dev uv run python manage.py runserver
```

Open http://localhost:8000/?admin=dev to unlock admin mode. If port 8000 is taken, pass another one, e.g. `runserver 127.0.0.1:8010`.

To build and run the image from your checkout instead of pulling it, use `docker compose up -d --build`.

## Running tests

```sh
uv run pytest                          # unit and view tests (events/tests)
uv run playwright install chromium     # once, for e2e
uv run pytest e2e                      # Playwright browser tests against a live server
uv run pytest e2e --headed --slowmo 300  # watch them run
```

`uv run pytest` doesn't run `e2e/`, so unit runs don't need browsers. The e2e fixtures (`e2e/conftest.py`) provide `admin_page` (admin mode already unlocked) and `attendee_page_factory` (each call gives a separate browser context, so a separate attendee). GitHub Actions runs both on every push and pull request.

Production-readiness check: `DEBUG=0 SECRET_KEY=x SITE_URL=https://example.org uv run python manage.py check --deploy`. The HSTS subdomain/preload and SSL-redirect warnings are intentional, and the SECRET_KEY warning goes away with a real key.

## Project layout

```
config/              settings, urls, wsgi (test_settings.py for pytest)
events/              the single Django app
  models.py          Event, Category, Item, CustomField, Attendee, FieldValue, Claim, SiteSettings
  middleware.py      attendee cookie, admin key and site settings middleware
  context_processors.py  site settings for every template
  permissions.py     admin_required, can_edit
  services.py        transactional slot claiming, custom items, slugs
  urls_public.py     attendee routes (including the /<slug>/ catch-all)
  urls_manage.py     admin routes under /manage/
  views/             public.py (attendees), sheet.py (signup sheet), manage.py (admin), health.py
  templatetags/      sheet helpers (slot counts, date formatting)
  templates/events/  pages and htmx partials
  templates/         404, 403 and 500 pages (500 is self-contained)
  migrations/        database migrations (applied on container start)
  tests/             unit and view tests
e2e/                 Playwright end-to-end tests
static/              css/app.css, js/app.js, vendored htmx, Pico CSS and fonts (vendor/fonts/)
docker/              entrypoint.sh: make /data writable, drop to the unprivileged app user, migrate, start gunicorn
.github/workflows/   ci.yml (tests), docker.yml (multi-arch image to GHCR)
Dockerfile           multi-stage image build (uv, static files collected at build)
compose.yaml         single-service Compose file with a data volume
gunicorn.conf.py     server settings; logs paths without query strings so ?admin= keys stay out of logs
railway.json         Railway build and deploy config
```

## License

MIT, see [LICENSE](LICENSE). Vendored htmx, Pico CSS and fonts keep their own licenses, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
