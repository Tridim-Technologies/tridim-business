import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization

from .models import (
    Job,
    JobAssignment,
    JobDueDateHistory,
    JobNote,
    JobStatusHistory,
    Quotation,
)


class JobDeliveryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="job-owner", password="a-long-test-password"
        )
        self.operations = user_model.objects.create_user(
            username="job-ops", password="a-long-test-password"
        )
        self.employee = user_model.objects.create_user(
            username="job-employee", password="a-long-test-password"
        )
        self.finance = user_model.objects.create_user(
            username="job-finance", password="a-long-test-password"
        )
        self.outsider = user_model.objects.create_user(
            username="job-outsider", password="a-long-test-password"
        )
        self.other_employee = user_model.objects.create_user(
            username="other-employee", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Job Org")
        self.other_organization = Organization.objects.create(name="Other Job Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
            (self.employee, Membership.Role.EMPLOYEE),
            (self.finance, Membership.Role.FINANCE),
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
            organization=self.organization, name="Job Customer", created_by=self.owner
        )
        self.quotation = Quotation.objects.create(
            organization=self.organization,
            customer=customer,
            currency="KES",
            valid_until=date.today() + timedelta(days=7),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        self.job = Job.objects.create(
            organization=self.organization,
            customer=customer,
            source_quotation=self.quotation,
            created_by=self.owner,
        )
        JobStatusHistory.objects.create(
            job=self.job,
            previous_status="",
            status=self.job.status,
            actor=self.owner,
            note="Job created from accepted quotation",
        )
        self.list_url = reverse("jobs", args=[self.organization.pk])
        self.detail_url = reverse(
            "job-detail", args=[self.organization.pk, self.job.pk]
        )

    def request_json(self, url, data, user=None, method="post"):
        self.client.force_login(user or self.operations)
        return getattr(self.client, method)(
            url, data=json.dumps(data), content_type="application/json"
        )

    def test_members_list_jobs_and_nonmembers_cannot_probe_them(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [job["id"] for job in response.json()["results"]], [self.job.pk]
        )
        wrong_org = reverse("jobs", args=[self.other_organization.pk])
        self.assertEqual(self.client.get(wrong_org).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)

    def test_status_transitions_and_audit_history_are_controlled(self):
        invalid = self.request_json(
            self.detail_url, {"status": Job.Status.COMPLETED}, method="patch"
        )
        self.assertEqual(invalid.status_code, 409)
        response = self.request_json(
            self.detail_url,
            {"status": Job.Status.IN_PROGRESS, "note": "Work started"},
            method="patch",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Job.Status.IN_PROGRESS)
        self.assertEqual(
            response.json()["status_history"][-1]["actor"], self.operations.username
        )
        self.assertEqual(JobStatusHistory.objects.filter(job=self.job).count(), 2)
        self.request_json(
            self.detail_url, {"status": Job.Status.COMPLETED}, method="patch"
        )
        terminal = self.request_json(
            self.detail_url, {"status": Job.Status.IN_PROGRESS}, method="patch"
        )
        self.assertEqual(terminal.status_code, 409)

    def test_due_date_changes_keep_history(self):
        first_date = (timezone.localdate() + timedelta(days=5)).isoformat()
        response = self.request_json(
            self.detail_url, {"due_date": first_date}, method="patch"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["due_date"], first_date)
        cleared = self.request_json(self.detail_url, {"due_date": None}, method="patch")
        self.assertEqual(cleared.json()["due_date"], None)
        self.assertEqual(JobDueDateHistory.objects.filter(job=self.job).count(), 2)
        self.assertEqual(JobDueDateHistory.objects.first().actor, self.operations)

    def test_finance_can_read_but_cannot_change_delivery_state(self):
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        response = self.client.patch(
            self.detail_url,
            data=json.dumps({"status": Job.Status.IN_PROGRESS}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.OPEN)

    def test_assignment_requires_org_member_and_retains_assignment_history(self):
        url = reverse("job-assignment-create", args=[self.organization.pk, self.job.pk])
        invalid = self.request_json(url, {"username": self.other_employee.username})
        self.assertEqual(invalid.status_code, 400)
        assigned = self.request_json(url, {"username": self.employee.username})
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assertEqual(
            assigned.json()["assignments"][0]["user"], self.employee.username
        )
        self.client.force_login(self.employee)
        self.assertEqual(
            [job["id"] for job in self.client.get(self.list_url).json()["results"]],
            [self.job.pk],
        )

        assignment = JobAssignment.objects.get(job=self.job, user=self.employee)
        remove_url = reverse(
            "job-assignment-remove",
            args=[self.organization.pk, self.job.pk, assignment.pk],
        )
        self.assertEqual(self.request_json(remove_url, {}).status_code, 200)
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.unassigned_at)
        self.assertEqual(assignment.unassigned_by, self.operations)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.list_url).json()["results"], [])
        self.request_json(url, {"username": self.employee.username})
        self.assertEqual(JobAssignment.objects.filter(job=self.job).count(), 2)

        self.client.force_login(self.finance)
        denied = self.client.post(
            url,
            data=json.dumps({"username": self.employee.username}),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_only_assigned_employee_can_add_append_only_delivery_notes(self):
        assignment_url = reverse(
            "job-assignment-create", args=[self.organization.pk, self.job.pk]
        )
        self.request_json(assignment_url, {"username": self.employee.username})
        notes_url = reverse("job-note-create", args=[self.organization.pk, self.job.pk])
        response = self.request_json(
            notes_url, {"content": "Arrived on site"}, user=self.employee
        )
        self.assertEqual(response.status_code, 200, response.content)
        note = JobNote.objects.get(job=self.job)
        self.assertEqual(note.author, self.employee)
        self.assertEqual(response.json()["notes"][0]["content"], "Arrived on site")
        denied = self.request_json(
            notes_url, {"content": "Unrelated update"}, user=self.finance
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(JobNote.objects.count(), 1)

    def test_unassigned_employee_cannot_read_or_note_job(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        notes_url = reverse("job-note-create", args=[self.organization.pk, self.job.pk])
        self.assertEqual(
            self.client.post(
                notes_url,
                data=json.dumps({"content": "No assignment"}),
                content_type="application/json",
            ).status_code,
            404,
        )
