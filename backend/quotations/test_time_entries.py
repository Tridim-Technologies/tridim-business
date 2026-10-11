import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization

from .models import Job, JobAssignment, JobTimeEntry, JobTimeEntryHistory, Quotation


class JobTimeEntryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="time-owner", password="a-long-test-password"
        )
        self.operations = user_model.objects.create_user(
            username="time-ops", password="a-long-test-password"
        )
        self.employee = user_model.objects.create_user(
            username="time-employee", password="a-long-test-password"
        )
        self.other_employee = user_model.objects.create_user(
            username="other-time-employee", password="a-long-test-password"
        )
        self.finance = user_model.objects.create_user(
            username="time-finance", password="a-long-test-password"
        )
        self.sales = user_model.objects.create_user(
            username="time-sales", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Time Org")
        self.other_organization = Organization.objects.create(name="Other Time Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
            (self.employee, Membership.Role.EMPLOYEE),
            (self.other_employee, Membership.Role.EMPLOYEE),
            (self.finance, Membership.Role.FINANCE),
            (self.sales, Membership.Role.SALES),
        ):
            Membership.objects.create(
                user=user, organization=self.organization, role=role
            )
        Membership.objects.create(
            user=self.other_employee,
            organization=self.other_organization,
            role=Membership.Role.EMPLOYEE,
        )
        from customers.models import Customer

        customer = Customer.objects.create(
            organization=self.organization,
            name="Time Customer",
            created_by=self.owner,
        )
        quotation = Quotation.objects.create(
            organization=self.organization,
            customer=customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=7),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        self.job = Job.objects.create(
            organization=self.organization,
            customer=customer,
            source_quotation=quotation,
            created_by=self.owner,
        )
        self.other_job = Job.objects.create(
            organization=self.other_organization,
            customer=Customer.objects.create(
                organization=self.other_organization,
                name="Other Customer",
                created_by=self.owner,
            ),
            source_quotation=Quotation.objects.create(
                organization=self.other_organization,
                customer=Customer.objects.get(
                    organization=self.other_organization,
                    name="Other Customer",
                ),
                currency="KES",
                valid_until=timezone.localdate() + timedelta(days=7),
                created_by=self.owner,
                status=Quotation.Status.ACCEPTED,
            ),
            created_by=self.owner,
        )
        self.assign(self.employee, self.job)
        self.url = reverse("job-time-entries", args=[self.organization.pk, self.job.pk])

    def assign(self, user, job):
        return JobAssignment.objects.create(job=job, user=user, assigned_by=self.owner)

    def post(self, url, payload, user=None):
        self.client.force_login(user or self.employee)
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def payload(self, **overrides):
        return {
            "work_date": timezone.localdate().isoformat(),
            "hours": "7.50",
            "description": "Synthetic service visit",
            **overrides,
        }

    def create_entry(self, user=None, job=None, payload=None):
        url = reverse(
            "job-time-entries",
            args=[self.organization.pk, (job or self.job).pk],
        )
        response = self.post(url, payload or self.payload(), user=user)
        self.assertEqual(response.status_code, 201, response.content)
        return JobTimeEntry.objects.get(pk=response.json()["results"][0]["id"])

    def review_url(self, entry, organization=None, job=None):
        return reverse(
            "job-time-entry-review",
            args=[
                (organization or self.organization).pk,
                (job or self.job).pk,
                entry.pk,
            ],
        )

    def test_assigned_employee_submits_time_and_history_captures_snapshot(self):
        response = self.post(self.url, self.payload())
        self.assertEqual(response.status_code, 201, response.content)
        entry = JobTimeEntry.objects.get(pk=response.json()["results"][0]["id"])
        history = entry.history.get()
        self.assertEqual(entry.job, self.job)
        self.assertEqual(entry.employee, self.employee)
        self.assertEqual(entry.hours, Decimal("7.50"))
        self.assertEqual(entry.status, JobTimeEntry.Status.SUBMITTED)
        self.assertEqual(history.previous_status, "")
        self.assertEqual(history.status, JobTimeEntry.Status.SUBMITTED)
        self.assertEqual(history.actor, self.employee)

    def test_employee_can_only_view_their_own_entries_for_assigned_jobs(self):
        own_entry = self.create_entry()
        other_entry = JobTimeEntry.objects.create(
            job=self.job,
            employee=self.other_employee,
            work_date=timezone.localdate(),
            hours=Decimal("1.00"),
        )
        self.client.force_login(self.employee)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]], [own_entry.pk]
        )
        self.assertNotIn(
            other_entry.pk, [item["id"] for item in response.json()["results"]]
        )

    def test_manager_can_view_entries_but_finance_and_sales_cannot(self):
        entry = self.create_entry()
        self.client.force_login(self.operations)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], entry.pk)
        for user in (self.finance, self.sales):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_nonassigned_employee_and_cross_tenant_job_are_not_accessible(self):
        self.client.force_login(self.other_employee)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        other_url = reverse(
            "job-time-entries", args=[self.other_organization.pk, self.other_job.pk]
        )
        response = self.post(other_url, self.payload(), user=self.other_employee)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(JobTimeEntry.objects.count(), 0)

    def test_employee_must_be_assigned_to_submit_and_cancelled_job_rejects_time(self):
        self.assign(self.other_employee, self.job)
        self.client.force_login(self.other_employee)
        before_assignment = JobAssignment.objects.get(
            job=self.job, user=self.other_employee
        )
        before_assignment.unassigned_at = timezone.now()
        before_assignment.save(update_fields=["unassigned_at"])
        self.assertEqual(
            self.post(self.url, self.payload(), self.other_employee).status_code, 404
        )
        self.job.status = Job.Status.CANCELLED
        self.job.save(update_fields=["status"])
        self.assertEqual(
            self.post(self.url, self.payload(), self.employee).status_code, 409
        )
        self.assertEqual(JobTimeEntry.objects.count(), 0)

    def test_hours_must_be_positive_at_most_24_and_work_date_not_future(self):
        for values in (
            {"hours": "0"},
            {"hours": "24.01"},
            {"hours": "1.001"},
            {"hours": "-1"},
            {"work_date": (timezone.localdate() + timedelta(days=1)).isoformat()},
        ):
            with self.subTest(values=values):
                response = self.post(self.url, self.payload(**values))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(JobTimeEntry.objects.count(), 0)

    def test_rejection_requires_reason_and_rejected_entry_resubmits_with_history(self):
        entry = self.create_entry()
        rejected = self.post(
            self.review_url(entry), {"action": "reject"}, user=self.operations
        )
        self.assertEqual(rejected.status_code, 400)
        rejected = self.post(
            self.review_url(entry),
            {"action": "reject", "reason": "Please correct the date."},
            user=self.operations,
        )
        self.assertEqual(rejected.status_code, 200, rejected.content)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JobTimeEntry.Status.REJECTED)
        correction = self.payload(hours="6.25", description="Corrected visit")
        resubmitted = self.post(
            reverse(
                "job-time-entry-resubmit",
                args=[self.organization.pk, self.job.pk, entry.pk],
            ),
            correction,
        )
        self.assertEqual(resubmitted.status_code, 200, resubmitted.content)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JobTimeEntry.Status.SUBMITTED)
        self.assertEqual(entry.hours, Decimal("6.25"))
        history = list(entry.history.all())
        self.assertEqual(
            [item.status for item in history], ["submitted", "rejected", "submitted"]
        )
        self.assertEqual(history[1].reason, "Please correct the date.")
        self.assertEqual(history[1].hours, Decimal("7.50"))
        self.assertEqual(history[2].hours, Decimal("6.25"))

    def test_only_managers_can_approve_and_entries_can_be_reviewed_once(self):
        entry = self.create_entry()
        denied = self.post(
            self.review_url(entry), {"action": "approve"}, user=self.employee
        )
        self.assertEqual(denied.status_code, 403)
        approved = self.post(
            self.review_url(entry), {"action": "approve"}, user=self.operations
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JobTimeEntry.Status.APPROVED)
        self.assertEqual(entry.history.count(), 2)
        repeated = self.post(
            self.review_url(entry), {"action": "approve"}, user=self.owner
        )
        self.assertEqual(repeated.status_code, 409)

    def test_review_endpoint_does_not_find_another_organizations_entry(self):
        entry = self.create_entry()
        response = self.post(
            self.review_url(
                entry, organization=self.other_organization, job=self.other_job
            ),
            {"action": "approve"},
            user=self.owner,
        )
        self.assertEqual(response.status_code, 404)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JobTimeEntry.Status.SUBMITTED)

    def test_entry_history_preserves_every_status_and_actor(self):
        entry = self.create_entry()
        self.post(
            self.review_url(entry),
            {"action": "approve", "reason": "Reviewed"},
            user=self.owner,
        )
        response = self.client.get(self.url)
        payload = response.json()["results"][0]
        self.assertEqual(
            [item["status"] for item in payload["history"]],
            ["submitted", "approved"],
        )
        self.assertEqual(payload["history"][1]["actor"], self.owner.username)
        self.assertEqual(JobTimeEntryHistory.objects.filter(entry=entry).count(), 2)
