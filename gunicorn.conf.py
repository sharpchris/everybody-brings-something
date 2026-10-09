"""Gunicorn settings (auto-loaded from the working directory)."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
accesslog = "-"
# %(U)s is the path without the query string, so ?admin=<key> never reaches the logs.
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(b)s %(L)ss'
# gunicorn 26 opens a control socket under $HOME by default; it isn't needed here and
# the container's non-root user can't write there.
control_socket_disable = True
