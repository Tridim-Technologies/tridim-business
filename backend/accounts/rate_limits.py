import hashlib
import hmac
import ipaddress
import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import EndpointRateLimitBucket


def client_address(request):
    """Use the socket peer; do not trust caller-supplied forwarding headers."""
    address = request.META.get("REMOTE_ADDR", "").strip()
    try:
        return ipaddress.ip_address(address).compressed
    except ValueError:
        return address[:128] or "unknown"


def _key_digest(scope, value):
    message = f"{scope}\0{value}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def consume_rate_limit(scope, value, *, limit, window_seconds, now=None):
    """Consume one slot in a database-backed fixed window shared by app instances."""
    now = now or timezone.now()
    digest = _key_digest(scope, value)
    window = timedelta(seconds=window_seconds)
    retention = timedelta(seconds=settings.ENDPOINT_RATE_LIMIT_BUCKET_RETENTION_SECONDS)

    with transaction.atomic():
        bucket, _ = EndpointRateLimitBucket.objects.select_for_update().get_or_create(
            key_digest=digest,
            defaults={
                "window_started_at": now,
                "request_count": 0,
                "expires_at": now + retention,
            },
        )
        if bucket.window_started_at + window <= now:
            bucket.window_started_at = now
            bucket.request_count = 0

        if bucket.request_count >= limit:
            retry_after = max(
                1,
                math.ceil((bucket.window_started_at + window - now).total_seconds()),
            )
            return False, retry_after

        bucket.request_count += 1
        bucket.expires_at = now + retention
        bucket.save(update_fields=("window_started_at", "request_count", "expires_at"))
    return True, 0


def clear_rate_limit(scope, value):
    EndpointRateLimitBucket.objects.filter(
        key_digest=_key_digest(scope, value)
    ).delete()
