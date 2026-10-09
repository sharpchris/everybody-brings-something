#!/bin/sh
# Make the data directory writable, drop to the app user, apply database migrations,
# then start gunicorn (settings in /app/gunicorn.conf.py).
# Arguments run instead of gunicorn, e.g. `docker compose run --rm web python manage.py shell`.
set -e

APP_UID=10001
APP_GID=10001

if [ "$(id -u)" = "0" ]; then
    # Volumes are often mounted root-owned (Railway, bind mounts, files from older images).
    data_dir=$(dirname "${DATABASE_PATH:-/data/db.sqlite3}")
    mkdir -p "$data_dir"
    if [ -n "$(find "$data_dir" \( ! -uid "$APP_UID" -o ! -gid "$APP_GID" \) -print -quit)" ]; then
        chown -R "$APP_UID:$APP_GID" "$data_dir"
    fi
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$0" "$@"
fi

cd /app
python manage.py migrate --noinput

if [ "$#" -gt 0 ]; then
    exec "$@"
fi
exec gunicorn config.wsgi
