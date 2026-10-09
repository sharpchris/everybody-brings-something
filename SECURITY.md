# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability** (a private security advisory). Don't open a public issue or pull request for a vulnerability.

Include what you found, how to reproduce it and the version or commit you tested. You should get a reply within a week. Once a fix is released, the advisory is published with credit to you unless you'd rather stay anonymous.

## Supported versions

Fixes go into the next release and the `latest` Docker image (which follows the main branch). Please upgrade before reporting, if you can.

## Scope

In scope:

- The application code in this repository: admin key handling, attendee cookies and edit permissions, private custom field values, CSRF, input handling and the HTTPS/proxy settings.
- The Dockerfile, entrypoint and published container image.

Out of scope:

- Deployments that ignore the documented setup, such as running with `DEBUG=1` in production, a weak or leaked `ADMIN_KEY` or `SECRET_KEY`, `BEHIND_PROXY=1` without a proxy in front, or a plain-HTTP install exposed to the internet.
- Vulnerabilities in dependencies (Django, gunicorn, htmx and so on) that don't affect this app specifically. Report those upstream.
- Attendees losing the ability to edit their own signups after clearing cookies. That's by design.
