"""`python manage.py admin_link`: print the link that unlocks admin mode."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Print the link that unlocks admin mode."

    def handle(self, *args, **options):
        if not settings.ADMIN_KEY:
            raise CommandError("Admin mode is off (ADMIN_KEY=off).")
        base = settings.SITE_URL or "http://localhost:8000"
        self.stdout.write(f"{base}/?admin={settings.ADMIN_KEY}")
