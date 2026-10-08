import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.conf import settings

from .models import Membership
from .rate_limits import clear_rate_limit, client_address, consume_rate_limit


def _too_many_requests(retry_after):
    response = JsonResponse(
        {"detail": "Too many login attempts. Try again later."}, status=429
    )
    response["Retry-After"] = str(retry_after)
    return response


def _organizations(user):
    return [
        {"id": str(m.organization_id), "name": m.organization.name, "role": m.role}
        for m in Membership.objects.filter(user=user)
        .select_related("organization")
        .order_by("organization__name")
    ]


@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_http_methods(["GET"])
def organizations_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    return JsonResponse({"results": _organizations(request.user)})


@require_http_methods(["GET", "POST", "DELETE"])
def session_view(request):
    if request.method == "GET":
        if not request.user.is_authenticated:
            return JsonResponse({"authenticated": False}, status=401)
        return JsonResponse(
            {
                "authenticated": True,
                "user": {
                    "id": request.user.pk,
                    "username": request.user.get_username(),
                },
                "organizations": _organizations(request.user),
            }
        )
    if request.method == "POST":
        ip = client_address(request)
        ip_allowed, ip_retry = consume_rate_limit(
            "login-ip",
            ip,
            limit=settings.LOGIN_ATTEMPTS_PER_IP,
            window_seconds=settings.LOGIN_ATTEMPT_WINDOW_SECONDS,
        )
        if not ip_allowed:
            return _too_many_requests(ip_retry)
        content_length = request.META.get("CONTENT_LENGTH")
        if content_length:
            try:
                if int(content_length) > settings.LOGIN_MAX_REQUEST_BYTES:
                    return JsonResponse(
                        {"detail": "Request body is too large."}, status=413
                    )
            except ValueError:
                return JsonResponse({"detail": "Invalid Content-Length."}, status=400)
        if len(request.body) > settings.LOGIN_MAX_REQUEST_BYTES:
            return JsonResponse({"detail": "Request body is too large."}, status=413)
        try:
            credentials = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"detail": "Invalid JSON."}, status=400)
        if not isinstance(credentials, dict):
            return JsonResponse({"detail": "A JSON object is required."}, status=400)
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        if (
            not isinstance(username, str)
            or len(username) > 150
            or not isinstance(password, str)
        ):
            return JsonResponse({"detail": "Invalid username or password."}, status=400)
        identity_key = f"{ip}\0{username.casefold()}"
        identity_allowed, identity_retry = consume_rate_limit(
            "login-identity-ip",
            identity_key,
            limit=settings.LOGIN_ATTEMPTS_PER_IDENTITY_IP,
            window_seconds=settings.LOGIN_ATTEMPT_WINDOW_SECONDS,
        )
        if not identity_allowed:
            return _too_many_requests(identity_retry)
        user = authenticate(
            request,
            username=username,
            password=password,
        )
        if user is None:
            return JsonResponse({"detail": "Invalid username or password."}, status=400)
        clear_rate_limit("login-identity-ip", identity_key)
        login(request, user)
        return JsonResponse(
            {
                "authenticated": True,
                "user": {"id": user.pk, "username": user.get_username()},
                "organizations": _organizations(user),
            }
        )
    logout(request)
    return JsonResponse({"authenticated": False})
