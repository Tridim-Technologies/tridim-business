from django.db import DatabaseError, connections
from django.http import HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def health_live_view(request):
    """Report that the web process can serve a request without checking dependencies."""
    return HttpResponse("ok", content_type="text/plain")


@require_GET
def health_ready_view(request):
    """Report whether the default database accepts a connection."""
    try:
        connections["default"].ensure_connection()
    except DatabaseError:
        return HttpResponse("unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
