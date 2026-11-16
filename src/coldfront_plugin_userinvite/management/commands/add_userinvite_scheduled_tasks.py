import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Register periodic Django-Q tasks for the userinvite plugin."

    def handle(self, *args, **options):
        date = timezone.now() + datetime.timedelta(days=1)
        date = date.replace(hour=0, minute=0, second=0, microsecond=0)

        _, created = Schedule.objects.get_or_create(
            func="coldfront_plugin_userinvite.tasks.expire_stale_invitations",
            defaults={
                "schedule_type": Schedule.DAILY,
                "next_run": date,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    "Scheduled daily task: "
                    "coldfront_plugin_userinvite.tasks.expire_stale_invitations"
                )
            )
        else:
            self.stdout.write(
                "Task already scheduled: "
                "coldfront_plugin_userinvite.tasks.expire_stale_invitations"
            )
