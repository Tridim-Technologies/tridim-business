import hashlib
import json
import logging
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Membership, Organization, OrganizationInvitation
from .rate_limits import client_address, consume_rate_limit
from .views import _organizations

INVITATION_TTL = timedelta(days=7)
MAX_BODY_BYTES = 4096
logger = logging.getLogger(__name__)


def _invitation_manager(membership):
    return membership.role in {Membership.Role.OWNER, Membership.Role.ADMIN}


def _may_invite_role(membership, role):
    if role == Membership.Role.OWNER:
        return False
    if role == Membership.Role.ADMIN and membership.role != Membership.Role.OWNER:
        return False
    return _invitation_manager(membership)


def _json_object(request):
    if len(request.body) > MAX_BODY_BYTES:
        return None, JsonResponse({"detail": "Request body is too large."}, status=413)
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"detail": "A JSON object is required."}, status=400)
    return data, None


def _invitation_payload(invitation):
    return {
        "id": invitation.pk,
        "organization": str(invitation.organization_id),
        "organization_name": invitation.organization.name,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.effective_status(),
        "invited_by": invitation.invited_by.get_username(),
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
        "accepted_at": invitation.accepted_at,
        "revoked_at": invitation.revoked_at,
    }


def _token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_invitation_email(invitation, token):
    if not settings.INVITATION_EMAIL_ENABLED or not settings.INVITATION_BASE_URL:
        return False
    if settings.EMAIL_BACKEND not in {
        "django.core.mail.backends.smtp.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
    }:
        return False
    role_label = dict(Membership.Role.choices).get(invitation.role, invitation.role)
    base_url = settings.INVITATION_BASE_URL.rstrip("/") + "/"
    invitation_url = f"{base_url}#invite={quote(token, safe='')}"
    expires_at = timezone.localtime(invitation.expires_at).strftime(
        "%B %d, %Y %H:%M %Z"
    )
    body = (
        f"You have been invited to join {invitation.organization.name} "
        f"as {role_label}.\n\n"
        f"Accept the invitation: {invitation_url}\n\n"
        f"This single-use link expires on {expires_at}. If you were not expecting "
        "this invitation, you can ignore this message.\n\n"
        "Accepting an invitation does not independently verify ownership of the "
        "email address."
    )
    try:
        delivered = send_mail(
            subject=f"Invitation to join {invitation.organization.name}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
    except Exception as error:
        # Keep the failure path usable without logging addresses, tokens, or
        # provider exception text that might contain sensitive delivery data.
        logger.warning(
            "Invitation email delivery failed for invitation %s (%s)",
            invitation.pk,
            type(error).__name__,
        )
        return False
    return delivered == 1


def _limited(request):
    allowed, retry_after = consume_rate_limit(
        "invitation-accept-ip",
        client_address(request),
        limit=30,
        window_seconds=900,
    )
    if allowed:
        return None
    response = JsonResponse(
        {"detail": "Too many invitation attempts. Try again later."}, status=429
    )
    response["Retry-After"] = str(retry_after)
    return response


def _user_payload(user):
    return {
        "authenticated": True,
        "user": {
            "id": user.pk,
            "username": user.get_username(),
            "email": user.email,
        },
        "organizations": _organizations(user),
    }


def _accept_response(user, invitation):
    return JsonResponse(
        {
            **_user_payload(user),
            "invitation": {
                "organization": str(invitation.organization_id),
                "organization_name": invitation.organization.name,
                "role": invitation.role,
            },
        }
    )


@require_http_methods(["GET", "POST"])
def organization_invitations_view(request, organization_id):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    membership = (
        Membership.objects.filter(user=request.user, organization_id=organization_id)
        .select_related("organization")
        .first()
    )
    if membership is None:
        return JsonResponse({"detail": "Organization not found."}, status=404)
    if not _invitation_manager(membership):
        return JsonResponse(
            {"detail": "You do not have permission to manage invitations."},
            status=403,
        )

    if request.method == "GET":
        invitations = OrganizationInvitation.objects.filter(
            organization_id=organization_id
        ).select_related("organization", "invited_by")[:100]
        return JsonResponse(
            {"results": [_invitation_payload(item) for item in invitations]}
        )

    data, error = _json_object(request)
    if error:
        return error
    if set(data) != {"email", "role"}:
        return JsonResponse(
            {"detail": "Provide only an email address and an organization role."},
            status=400,
        )
    raw_email = data.get("email")
    role = data.get("role")
    if not isinstance(raw_email, str) or len(raw_email) > 254:
        return JsonResponse({"email": ["Enter a valid email address."]}, status=400)
    email = raw_email.strip().casefold()
    try:
        validate_email(email)
    except DjangoValidationError:
        return JsonResponse({"email": ["Enter a valid email address."]}, status=400)
    role_choices = {value for value, _label in Membership.Role.choices}
    if role not in role_choices:
        return JsonResponse({"role": ["Choose a valid organization role."]}, status=400)
    if not _may_invite_role(membership, role):
        return JsonResponse(
            {"detail": "You cannot invite someone to that organization role."},
            status=403,
        )

    current_member = Membership.objects.filter(
        organization_id=organization_id, user__email__iexact=email
    ).exists()
    if current_member:
        return JsonResponse(
            {"detail": "An account with this email is already a member."}, status=409
        )

    token = secrets.token_urlsafe(32)
    now = timezone.now()
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            OrganizationInvitation.objects.filter(
                organization_id=organization_id,
                email=email,
                status=OrganizationInvitation.Status.PENDING,
                expires_at__lte=now,
            ).update(status=OrganizationInvitation.Status.EXPIRED)
            invitation = OrganizationInvitation.objects.create(
                organization_id=organization_id,
                email=email,
                role=role,
                token_digest=_token_digest(token),
                invited_by=request.user,
                expires_at=now + INVITATION_TTL,
            )
    except IntegrityError:
        return JsonResponse(
            {"detail": "A pending invitation already exists for this email."},
            status=409,
        )

    email_sent = _send_invitation_email(invitation, token)
    response = {
        "invitation": _invitation_payload(invitation),
        "email_sent": email_sent,
        "share_once": not email_sent,
    }
    if not email_sent:
        response["token"] = token
    return JsonResponse(response, status=201)


@require_http_methods(["POST"])
def organization_invitation_revoke_view(request, organization_id, invitation_id):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    membership = Membership.objects.filter(
        user=request.user, organization_id=organization_id
    ).first()
    if membership is None:
        return JsonResponse({"detail": "Organization not found."}, status=404)
    if not _invitation_manager(membership):
        return JsonResponse(
            {"detail": "You do not have permission to manage invitations."},
            status=403,
        )
    data, error = _json_object(request)
    if error:
        return error
    if data:
        return JsonResponse({"detail": "An empty JSON object is required."}, status=400)

    with transaction.atomic():
        invitation = (
            OrganizationInvitation.objects.select_for_update()
            .filter(pk=invitation_id, organization_id=organization_id)
            .first()
        )
        if invitation is None:
            return JsonResponse({"detail": "Invitation not found."}, status=404)
        if invitation.status != OrganizationInvitation.Status.PENDING:
            return JsonResponse(
                {"detail": "Only pending invitations can be revoked."}, status=409
            )
        if invitation.expires_at <= timezone.now():
            invitation.status = OrganizationInvitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            return JsonResponse({"detail": "This invitation has expired."}, status=410)
        invitation.status = OrganizationInvitation.Status.REVOKED
        invitation.revoked_by = request.user
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["status", "revoked_by", "revoked_at"])
    return JsonResponse(_invitation_payload(invitation))


def _load_invitation(token, *, lock=False):
    if not isinstance(token, str) or len(token) > 128 or not token:
        return None
    invitations = OrganizationInvitation.objects.select_related(
        "organization", "invited_by"
    )
    if lock:
        invitations = invitations.select_for_update()
    return invitations.filter(token_digest=_token_digest(token)).first()


@require_http_methods(["POST"])
def invitation_inspect_view(request):
    limited = _limited(request)
    if limited:
        return limited
    data, error = _json_object(request)
    if error:
        return error
    if set(data) != {"token"}:
        return JsonResponse({"detail": "Provide the invitation token."}, status=400)
    invitation = _load_invitation(data["token"])
    if invitation is None:
        return JsonResponse({"detail": "Invitation not found."}, status=404)
    if invitation.effective_status() == OrganizationInvitation.Status.EXPIRED:
        OrganizationInvitation.objects.filter(pk=invitation.pk).update(
            status=OrganizationInvitation.Status.EXPIRED
        )
        return JsonResponse({"detail": "This invitation has expired."}, status=410)
    if invitation.status != OrganizationInvitation.Status.PENDING:
        return JsonResponse(
            {"detail": "This invitation is no longer available."}, status=410
        )
    return JsonResponse(
        {
            "email": invitation.email,
            "role": invitation.role,
            "organization_name": invitation.organization.name,
            "expires_at": invitation.expires_at,
        }
    )


@require_http_methods(["POST"])
def invitation_accept_view(request):
    limited = _limited(request)
    if limited:
        return limited
    data, error = _json_object(request)
    if error:
        return error
    authenticated = request.user.is_authenticated
    expected_keys = {"token"} if authenticated else {"token", "username", "password"}
    if set(data) != expected_keys:
        return JsonResponse(
            {"detail": "Invitation acceptance details are incomplete."}, status=400
        )
    token = data.get("token")
    if not isinstance(token, str):
        return JsonResponse({"detail": "Invitation not found."}, status=404)

    User = get_user_model()
    username_field_name = User.USERNAME_FIELD
    email_field_name = User.get_email_field_name()
    user = request.user if authenticated else None
    if authenticated:
        if not user.is_active or user.is_staff or user.is_superuser:
            return JsonResponse(
                {"detail": "This account cannot join an organization."}, status=403
            )
    else:
        username = data.get("username")
        password = data.get("password")
        if (
            not isinstance(username, str)
            or not username.strip()
            or not isinstance(password, str)
            or len(password) > 128
        ):
            return JsonResponse(
                {"detail": "Enter a username and password."}, status=400
            )

    with transaction.atomic():
        invitation = _load_invitation(token, lock=True)
        if invitation is None:
            return JsonResponse({"detail": "Invitation not found."}, status=404)
        if invitation.status == OrganizationInvitation.Status.ACCEPTED:
            if user and invitation.accepted_by_id == user.pk:
                return _accept_response(user, invitation)
            return JsonResponse(
                {"detail": "This invitation has already been used."}, status=409
            )
        if invitation.status != OrganizationInvitation.Status.PENDING:
            return JsonResponse(
                {"detail": "This invitation is no longer available."}, status=410
            )
        if invitation.expires_at <= timezone.now():
            invitation.status = OrganizationInvitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            return JsonResponse({"detail": "This invitation has expired."}, status=410)

        if authenticated:
            if (user.email or "").strip().casefold() != invitation.email.casefold():
                return JsonResponse(
                    {
                        "detail": "Sign in with the email address this invitation was sent to."
                    },
                    status=403,
                )
        else:
            existing = User.objects.filter(
                **{f"{email_field_name}__iexact": invitation.email}
            ).first()
            if existing is not None:
                return JsonResponse(
                    {
                        "detail": "An account already uses this email. Sign in to accept the invitation."
                    },
                    status=409,
                )
            username_field = User._meta.get_field(username_field_name)
            try:
                username = username_field.clean(username.strip(), None)
            except DjangoValidationError as exc:
                return JsonResponse({"username": exc.messages}, status=400)
            if User.objects.filter(
                **{f"{username_field_name}__iexact": username}
            ).exists():
                return JsonResponse(
                    {"username": ["This username is already in use."]}, status=400
                )
            user_kwargs = {
                username_field_name: username,
                email_field_name: invitation.email,
            }
            candidate = User(**user_kwargs)
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                return JsonResponse({"password": exc.messages}, status=400)
            user = User.objects.create_user(password=password, **user_kwargs)

        existing_membership = Membership.objects.filter(
            organization=invitation.organization, user=user
        ).first()
        if (
            existing_membership is not None
            and existing_membership.role != invitation.role
        ):
            return JsonResponse(
                {
                    "detail": "This account already has a different role in the organization."
                },
                status=409,
            )
        if existing_membership is None:
            Membership.objects.create(
                organization=invitation.organization,
                user=user,
                role=invitation.role,
            )
        invitation.status = OrganizationInvitation.Status.ACCEPTED
        invitation.accepted_by = user
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_by", "accepted_at"])

    if not authenticated:
        login(request, user)
    return _accept_response(user, invitation)
