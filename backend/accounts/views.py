import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import Membership


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
        try:
            credentials = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"detail": "Invalid JSON."}, status=400)
        if not isinstance(credentials, dict):
            return JsonResponse({"detail": "A JSON object is required."}, status=400)
        user = authenticate(
            request,
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
        )
        if user is None:
            return JsonResponse({"detail": "Invalid username or password."}, status=400)
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
