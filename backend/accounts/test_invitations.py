import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Membership, Organization, OrganizationInvitation


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class OrganizationInvitationApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="invite-owner", email="owner@example.com", password="Testpass!384"
        )
        self.admin = User.objects.create_user(
            username="invite-admin", email="admin@example.com", password="Testpass!384"
        )
        self.employee = User.objects.create_user(
            username="invite-employee",
            email="employee@example.com",
            password="Testpass!384",
        )
        self.outsider = User.objects.create_user(
            username="invite-outsider",
            email="other@example.com",
            password="Testpass!384",
        )
        self.organization = Organization.objects.create(name="Invite Services")
        self.other_organization = Organization.objects.create(name="Other Services")
        Membership.objects.create(
            user=self.owner, organization=self.organization, role=Membership.Role.OWNER
        )
        Membership.objects.create(
            user=self.admin, organization=self.organization, role=Membership.Role.ADMIN
        )
        Membership.objects.create(
            user=self.employee,
            organization=self.organization,
            role=Membership.Role.EMPLOYEE,
        )
        Membership.objects.create(
            user=self.outsider,
            organization=self.other_organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.list_url = reverse("organization-invitations", args=[self.organization.id])

    def post(self, url, payload, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def create_invitation(
        self, email="new-member@example.com", role="employee", user=None
    ):
        response = self.post(
            self.list_url, {"email": email, "role": role}, user or self.owner
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def accept_url(self, name="invitation-accept"):
        return reverse(name)

    def test_owner_creates_single_use_invitation_and_token_is_never_listed(self):
        result = self.create_invitation(email="  New.Member@Example.com  ")
        invitation = OrganizationInvitation.objects.get(pk=result["invitation"]["id"])
        self.assertEqual(invitation.email, "new.member@example.com")
        self.assertEqual(invitation.role, Membership.Role.EMPLOYEE)
        self.assertNotEqual(invitation.token_digest, result["token"])
        self.assertLess(
            abs(
                (invitation.expires_at - invitation.created_at).total_seconds()
                - 7 * 86400
            ),
            1,
        )
        self.assertTrue(result["share_once"])

        self.client.force_login(self.owner)
        listed = self.client.get(self.list_url).json()["results"]
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])
        self.assertNotIn("token_digest", listed[0])

        duplicate = self.post(
            self.list_url,
            {"email": "NEW.MEMBER@example.com", "role": "employee"},
            self.admin,
        )
        self.assertEqual(duplicate.status_code, 409)

    @override_settings(
        INVITATION_EMAIL_ENABLED=True,
        INVITATION_BASE_URL="http://app.example.test",
        DEFAULT_FROM_EMAIL="Tridim Business <no-reply@example.test>",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_successful_email_hides_token_from_create_response(self):
        self.assertTrue(settings.INVITATION_EMAIL_ENABLED)
        self.assertEqual(
            settings.EMAIL_BACKEND,
            "django.core.mail.backends.locmem.EmailBackend",
        )
        result = self.create_invitation("new-member@example.com")

        self.assertTrue(result["email_sent"], result)
        self.assertFalse(result["share_once"])
        self.assertNotIn("token", result)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["new-member@example.com"])
        self.assertEqual(message.from_email, "Tridim Business <no-reply@example.test>")
        self.assertIn("Invite Services", message.subject)
        self.assertIn("Employee", message.body)
        self.assertIn("expires", message.body.lower())

        invite_link = next(
            line.split(": ", 1)[1]
            for line in message.body.splitlines()
            if line.startswith("Accept the invitation: ")
        )
        self.assertTrue(invite_link.startswith("http://app.example.test/#invite="))
        token = invite_link.split("#invite=", 1)[1]
        invitation = OrganizationInvitation.objects.get(pk=result["invitation"]["id"])
        self.assertEqual(
            invitation.token_digest, hashlib.sha256(token.encode()).hexdigest()
        )
        self.assertNotIn(token, json.dumps(result))

    @override_settings(INVITATION_EMAIL_ENABLED=False)
    def test_disabled_email_keeps_manual_link_fallback(self):
        result = self.create_invitation()

        self.assertFalse(result["email_sent"])
        self.assertTrue(result["share_once"])
        self.assertTrue(result["token"])
        self.assertEqual(mail.outbox, [])

    @override_settings(
        INVITATION_EMAIL_ENABLED=True,
        INVITATION_BASE_URL="https://app.example.test",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    @patch(
        "accounts.invitation_views.send_mail",
        side_effect=OSError("private smtp details"),
    )
    def test_email_failure_keeps_invitation_and_returns_manual_fallback(
        self, _send_mail
    ):
        with self.assertLogs("accounts.invitation_views", level="WARNING") as captured:
            result = self.create_invitation()

        self.assertFalse(result["email_sent"])
        self.assertTrue(result["share_once"])
        self.assertTrue(result["token"])
        self.assertIn("OSError", captured.output[0])
        self.assertNotIn("private smtp details", captured.output[0])
        invitation = OrganizationInvitation.objects.get(pk=result["invitation"]["id"])
        self.assertEqual(invitation.status, OrganizationInvitation.Status.PENDING)

    def test_role_grants_prevent_owner_and_admin_escalation(self):
        owner_admin = self.create_invitation("admin-candidate@example.com", "admin")
        self.assertEqual(owner_admin["invitation"]["role"], Membership.Role.ADMIN)
        forbidden = self.post(
            self.list_url,
            {"email": "owner-candidate@example.com", "role": "owner"},
            self.owner,
        )
        self.assertEqual(forbidden.status_code, 403)
        admin_promotion = self.post(
            self.list_url,
            {"email": "admin-candidate2@example.com", "role": "admin"},
            self.admin,
        )
        self.assertEqual(admin_promotion.status_code, 403)
        admin_ops = self.post(
            self.list_url,
            {"email": "ops-candidate@example.com", "role": "operations"},
            self.admin,
        )
        self.assertEqual(admin_ops.status_code, 201)

    def test_nonmanagers_and_other_organizations_cannot_manage_invitations(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(
            self.post(
                self.list_url,
                {"email": "nope@example.com", "role": "employee"},
            ).status_code,
            403,
        )
        other_url = reverse(
            "organization-invitations", args=[self.other_organization.id]
        )
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        self.assertEqual(self.client.get(other_url).status_code, 403)

    def test_new_invitee_creates_account_and_membership_then_acceptance_is_idempotent(
        self,
    ):
        result = self.create_invitation()
        inspect = self.post(reverse("invitation-inspect"), {"token": result["token"]})
        self.assertEqual(inspect.status_code, 200)
        self.assertEqual(inspect.json()["email"], "new-member@example.com")
        self.assertEqual(inspect.json()["organization_name"], "Invite Services")

        self.client.logout()
        accepted = self.post(
            self.accept_url(),
            {
                "token": result["token"],
                "username": "new-member",
                "password": "A-long-test-password-839!",
            },
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertTrue(accepted.json()["authenticated"])
        new_user = get_user_model().objects.get(username="new-member")
        self.assertEqual(new_user.email, "new-member@example.com")
        self.assertEqual(
            Membership.objects.get(user=new_user, organization=self.organization).role,
            Membership.Role.EMPLOYEE,
        )
        invitation = OrganizationInvitation.objects.get(pk=result["invitation"]["id"])
        self.assertEqual(invitation.status, OrganizationInvitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_by, new_user)

        repeated = self.post(self.accept_url(), {"token": result["token"]})
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(Membership.objects.filter(user=new_user).count(), 1)

    def test_existing_account_must_sign_in_with_matching_email(self):
        result = self.create_invitation("other@example.com", "finance")
        self.client.logout()
        signup_attempt = self.post(
            self.accept_url(),
            {
                "token": result["token"],
                "username": "duplicate-user",
                "password": "A-long-test-password-839!",
            },
        )
        self.assertEqual(signup_attempt.status_code, 409)

        self.client.force_login(self.owner)
        wrong_user = self.post(self.accept_url(), {"token": result["token"]})
        self.assertEqual(wrong_user.status_code, 403)

        self.client.force_login(self.outsider)
        accepted = self.post(self.accept_url(), {"token": result["token"]})
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertTrue(
            Membership.objects.filter(
                user=self.outsider,
                organization=self.organization,
                role=Membership.Role.FINANCE,
            ).exists()
        )

    def test_expired_invitation_is_rejected_and_marked_expired(self):
        result = self.create_invitation()
        invitation = OrganizationInvitation.objects.get(pk=result["invitation"]["id"])
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])

        response = self.post(reverse("invitation-inspect"), {"token": result["token"]})
        self.assertEqual(response.status_code, 410)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, OrganizationInvitation.Status.EXPIRED)

    def test_revoked_invitation_cannot_be_accepted(self):
        result = self.create_invitation()
        revoke_url = reverse(
            "organization-invitation-revoke",
            args=[self.organization.id, result["invitation"]["id"]],
        )
        revoked = self.post(revoke_url, {}, self.admin)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(
            revoked.json()["status"], OrganizationInvitation.Status.REVOKED
        )
        self.client.logout()
        accepted = self.post(
            self.accept_url(),
            {
                "token": result["token"],
                "username": "revoked-member",
                "password": "A-long-test-password-839!",
            },
        )
        self.assertEqual(accepted.status_code, 410)
        self.assertFalse(
            get_user_model().objects.filter(username="revoked-member").exists()
        )

    def test_signup_rejects_invalid_password_and_username(self):
        result = self.create_invitation()
        self.client.logout()
        weak_password = self.post(
            self.accept_url(),
            {"token": result["token"], "username": "weak-member", "password": "123"},
        )
        self.assertEqual(weak_password.status_code, 400)
        self.assertIn("password", weak_password.json())
        self.assertFalse(
            get_user_model().objects.filter(username="weak-member").exists()
        )

    def test_invitation_identifiers_cannot_be_changed_by_invitee(self):
        result = self.create_invitation()
        self.client.logout()
        response = self.post(
            self.accept_url(),
            {
                "token": result["token"],
                "username": "tampered-member",
                "password": "A-long-test-password-839!",
                "organization_id": str(self.other_organization.id),
                "role": Membership.Role.OWNER,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            get_user_model().objects.filter(username="tampered-member").exists()
        )
