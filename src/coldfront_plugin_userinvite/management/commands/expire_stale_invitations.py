from django.core.management.base import BaseCommand

from coldfront_plugin_userinvite.tasks import expire_stale_invitations


class Command(BaseCommand):
    help = "Mark pending invitations that have passed their expiry time as expired."

    def handle(self, *args, **options):
        result = expire_stale_invitations()
        self.stdout.write(self.style.SUCCESS(result))
