import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from .models import LeaveRequest, LeaveRequestHistory


class LeaveRequestApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="leave-owner")
        self.employee = User.objects.create_user(username="leave-employee")
        self.other_employee = User.objects.create_user(username="leave-other")
        self.outsider = User.objects.create_user(username="leave-outsider")
        self.organization = Organization.objects.create(name="Leave Services")
        self.other_organization = Organization.objects.create(name="Other Services")
        self.owner_membership = Membership.objects.create(
            user=self.owner, organization=self.organization, role=Membership.Role.OWNER
        )
        self.employee_membership = Membership.objects.create(
            user=self.employee,
            organization=self.organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.other_membership = Membership.objects.create(
            user=self.other_employee,
            organization=self.organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.outsider_membership = Membership.objects.create(
            user=self.outsider,
            organization=self.other_organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.base_url = reverse("leave-requests", args=[self.organization.id])
        self.today = timezone.localdate()

    def payload(self, **overrides):
        return {
            "start_date": str(self.today + timedelta(days=5)),
            "end_date": str(self.today + timedelta(days=7)),
            "category": "annual",
            "note": "  Family   time  ",
            **overrides,
        }

    def post(self, path, payload, user):
        self.client.force_login(user)
        return self.client.post(
            path, data=json.dumps(payload), content_type="application/json"
        )

    def create_request(self, *, user=None, **overrides):
        response = self.post(
            self.base_url, self.payload(**overrides), user or self.employee
        )
        self.assertEqual(response.status_code, 201, response.content)
        return LeaveRequest.objects.get(pk=response.json()["id"])

    def transition(self, leave_request, action, user, reason=""):
        path = reverse(
            "leave-request-transition",
            args=[self.organization.id, leave_request.id],
        )
        return self.post(path, {"action": action, "reason": reason}, user)

    def test_employee_submits_own_request_and_only_sees_own_history(self):
        leave_request = self.create_request()
        self.assertEqual(leave_request.membership, self.employee_membership)
        self.assertEqual(leave_request.note, "Family time")
        history = leave_request.history.get()
        self.assertEqual(history.action, LeaveRequestHistory.Action.SUBMITTED)
        self.assertEqual(history.actor, self.employee)

        self.client.force_login(self.employee)
        listing = self.client.get(self.base_url).json()["results"]
        self.assertEqual([item["id"] for item in listing], [leave_request.id])
        self.assertTrue(listing[0]["is_requester"])
        self.assertNotIn("membership_id", listing[0])

    def test_manager_can_list_requests_and_employee_cannot_view_another_request(self):
        leave_request = self.create_request()
        self.client.force_login(self.owner)
        listing = self.client.get(self.base_url).json()["results"]
        self.assertEqual(listing[0]["employee"], self.employee.username)
        self.assertFalse(listing[0]["is_requester"])

        detail = reverse(
            "leave-request-detail", args=[self.organization.id, leave_request.id]
        )
        self.client.force_login(self.other_employee)
        self.assertEqual(self.client.get(detail).status_code, 404)
        foreign_route = reverse(
            "leave-request-detail",
            args=[self.other_organization.id, leave_request.id],
        )
        self.assertEqual(self.client.get(foreign_route).status_code, 404)

    def test_requester_cannot_choose_another_membership(self):
        response = self.post(
            self.base_url,
            self.payload(membership_id=self.owner_membership.id),
            self.employee,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(LeaveRequest.objects.count(), 0)

    def test_rejects_invalid_dates_and_unreasonable_ranges(self):
        past = self.post(
            self.base_url,
            self.payload(start_date=str(self.today - timedelta(days=1))),
            self.employee,
        )
        self.assertEqual(past.status_code, 400)
        reversed_dates = self.post(
            self.base_url,
            self.payload(
                start_date=str(self.today + timedelta(days=8)),
                end_date=str(self.today + timedelta(days=7)),
            ),
            self.employee,
        )
        self.assertEqual(reversed_dates.status_code, 400)
        long_request = self.post(
            self.base_url,
            self.payload(end_date=str(self.today + timedelta(days=400))),
            self.employee,
        )
        self.assertEqual(long_request.status_code, 400)

    def test_overlapping_pending_or_approved_request_is_rejected(self):
        first = self.create_request()
        overlap = self.post(
            self.base_url,
            self.payload(
                start_date=str(first.end_date),
                end_date=str(first.end_date + timedelta(days=1)),
            ),
            self.employee,
        )
        self.assertEqual(overlap.status_code, 409)
        self.assertEqual(LeaveRequest.objects.count(), 1)

        self.transition(first, "reject", self.owner, "Coverage unavailable")
        after_rejection = self.post(
            self.base_url,
            self.payload(
                start_date=str(first.start_date), end_date=str(first.end_date)
            ),
            self.employee,
        )
        self.assertEqual(after_rejection.status_code, 201)

        approved_request = self.create_request(
            start_date=str(self.today + timedelta(days=25)),
            end_date=str(self.today + timedelta(days=27)),
        )
        self.transition(approved_request, "approve", self.owner)
        approved_overlap = self.post(
            self.base_url,
            self.payload(
                start_date=str(approved_request.start_date),
                end_date=str(approved_request.end_date),
            ),
            self.employee,
        )
        self.assertEqual(approved_overlap.status_code, 409)

    def test_manager_decision_is_audited_and_terminal(self):
        leave_request = self.create_request()
        response = self.transition(leave_request, "approve", self.owner)
        self.assertEqual(response.status_code, 200)
        leave_request.refresh_from_db()
        self.assertEqual(leave_request.status, LeaveRequest.Status.APPROVED)
        self.assertEqual(leave_request.reviewed_by, self.owner)
        self.assertIsNotNone(leave_request.reviewed_at)
        self.assertEqual(leave_request.history.count(), 2)
        self.assertEqual(
            self.transition(
                leave_request, "reject", self.owner, "Changed mind"
            ).status_code,
            409,
        )

    def test_rejection_requires_reason_and_self_review_is_denied(self):
        own_request = self.create_request(user=self.owner)
        self.assertEqual(
            self.transition(own_request, "approve", self.owner).status_code, 403
        )
        employee_request = self.create_request(
            start_date=str(self.today + timedelta(days=15)),
            end_date=str(self.today + timedelta(days=17)),
        )
        self.assertEqual(
            self.transition(employee_request, "reject", self.owner).status_code, 400
        )
        rejected = self.transition(
            employee_request, "reject", self.owner, "Insufficient coverage"
        )
        self.assertEqual(rejected.status_code, 200)
        employee_request.refresh_from_db()
        self.assertEqual(employee_request.status, LeaveRequest.Status.REJECTED)
        self.assertEqual(employee_request.decision_reason, "Insufficient coverage")
        self.assertEqual(
            employee_request.history.last().reason, "Insufficient coverage"
        )

    def test_employee_cannot_review_and_requester_can_cancel_only_pending(self):
        leave_request = self.create_request()
        self.assertEqual(
            self.transition(leave_request, "approve", self.other_employee).status_code,
            404,
        )
        self.assertEqual(
            self.transition(leave_request, "cancel", self.other_employee).status_code,
            404,
        )
        self.assertEqual(
            self.transition(leave_request, "cancel", self.employee).status_code, 200
        )
        leave_request.refresh_from_db()
        self.assertEqual(leave_request.status, LeaveRequest.Status.CANCELLED)
        self.assertEqual(leave_request.history.count(), 2)
        self.assertEqual(
            self.transition(leave_request, "cancel", self.employee).status_code, 409
        )

    def test_non_member_and_unauthenticated_access_are_denied(self):
        self.assertEqual(self.client.get(self.base_url).status_code, 401)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.base_url).status_code, 404)
