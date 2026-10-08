from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import EndpointRateLimitBucket
from invoicing.models import DarajaCallbackEvent


class Command(BaseCommand):
    help = (
        "Delete expired endpoint rate-limit buckets and old unmatched Daraja callbacks."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        bucket_count, _ = EndpointRateLimitBucket.objects.filter(
            expires_at__lt=now
        ).delete()
        cutoff = now - timedelta(
            seconds=settings.DARAJA_UNKNOWN_CALLBACK_RETENTION_SECONDS
        )
        event_count, _ = DarajaCallbackEvent.objects.filter(
            attempt__isnull=True, last_received_at__lt=cutoff
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {bucket_count} expired rate-limit records and "
                f"{event_count} old unmatched callback records."
            )
        )
