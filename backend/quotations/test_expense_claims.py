import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, SupportAccess
from customers.models import Customer
from invoicing.models import Invoice, Payment

from .models import (
    ExpenseClaim,
    ExpenseClaimHistory,
    Job,
    JobAssignment,
    Quotation,
)


class ExpenseClaimTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="expense-owner")
        self.admin = user_model.objects.create_user(username="expense-admin")
        self.ops = user_model.objects.create_user(username="expense-ops")
        self.employee = user_model.objects.create_user(username="expense-employee")
        self.other = user_model.objects.create_user(username="expense-other")
        self.finance = user_model.objects.create_user(username="expense-finance")
        self.sales = user_model.objects.create_user(username="expense-sales")
        self.support = user_model.objects.create_user(
            username="expense-support", is_staff=True
        )
        self.superuser = user_model.objects.create_superuser(
            username="expense-superuser", password="test-password"
        )
        self.organization = Organization.objects.create(name="Expense Org")
        self.other_organization = Organization.objects.create(name="Other Expense Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.admin, Membership.Role.ADMIN),
            (self.ops, Membership.Role.OPERATIONS),
            (self.employee, Membership.Role.EMPLOYEE),
            (self.other, Membership.Role.EMPLOYEE),
            (self.finance, Membership.Role.FINANCE),
            (self.sales, Membership.Role.SALES),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        Membership.objects.create(
            organization=self.other_organization,
            user=self.other,
            role=Membership.Role.EMPLOYEE,
        )
        self.job = self.make_job(self.organization)
        self.other_job = self.make_job(self.other_organization)
        self.assign(self.employee, self.job)
        self.url = reverse("expense-claims", args=[self.organization.pk])

    def make_job(self, organization):
        customer = Customer.objects.create(
            organization=organization, name="Synthetic customer", created_by=self.owner
        )
        quotation = Quotation.objects.create(
            organization=organization,
            customer=customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=7),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        return Job.objects.create(
            organization=organization,
            customer=customer,
            source_quotation=quotation,
            created_by=self.owner,
        )

    def assign(self, user, job):
        return JobAssignment.objects.create(job=job, user=user, assigned_by=self.owner)

    def request(self, method, url, payload=None, *, user=None):
        self.client.force_login(user or self.employee)
        if method == "get":
            return self.client.get(url)
        return getattr(self.client, method)(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def fields(self, **changes):
        return {
            "job_id": self.job.pk,
            "expense_date": timezone.localdate().isoformat(),
            "amount": "125.12345",
            "currency": "KES",
            "category": "travel",
            "merchant": "Synthetic merchant",
            "purpose": "Synthetic delivery visit",
            "missing_receipt_explanation": "Receipt unavailable in synthetic scenario",
            **changes,
        }

    def create(self, *, user=None, **changes):
        response = self.request("post", self.url, self.fields(**changes), user=user)
        self.assertEqual(response.status_code, 201, response.content)
        return ExpenseClaim.objects.get(pk=response.json()["id"])

    def detail_url(self, claim, organization=None):
        return reverse(
            "expense-claim-detail",
            args=[(organization or self.organization).pk, claim.pk],
        )

    def transition(self, claim, action, *, user=None, revision=None, reason=""):
        return self.request(
            "post",
            reverse("expense-claim-transition", args=[self.organization.pk, claim.pk]),
            {
                "action": action,
                "revision": revision if revision is not None else claim.revision,
                "reason": reason,
            },
            user=user,
        )

    def test_assigned_member_creates_submits_and_history_preserves_exact_values(self):
        claim = self.create()
        self.assertEqual(claim.organization, self.organization)
        self.assertEqual(claim.claimant, self.employee)
        self.assertEqual(claim.amount, Decimal("125.12345"))
        self.assertEqual(claim.status, ExpenseClaim.Status.DRAFT)
        self.assertEqual(claim.history.get().action, "create")
        response = self.transition(claim, "submit")
        self.assertEqual(response.status_code, 200, response.content)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.SUBMITTED)
        self.assertEqual(claim.version, 1)
        self.assertEqual(claim.revision, 2)
        self.assertEqual(
            list(claim.history.values_list("action", flat=True)), ["create", "submit"]
        )
        self.assertEqual(claim.history.last().amount, Decimal("125.12345"))
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cross_tenant_unassigned_and_client_authority_fields_are_denied(self):
        for changes in (
            {"job_id": self.other_job.pk},
            {"organization": str(self.other_organization.pk)},
            {"claimant": self.other.pk},
            {"has_receipt": True},
            {"waived": True},
        ):
            with self.subTest(changes=changes):
                response = self.request("post", self.url, self.fields(**changes))
                self.assertIn(response.status_code, {400, 404})
        response = self.request("post", self.url, self.fields(), user=self.other)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ExpenseClaim.objects.count(), 0)

    def test_role_scoped_reads_and_finance_metadata_only(self):
        first = self.create()
        self.assign(self.other, self.job)
        second = self.create(user=self.other)
        self.assertEqual(
            [row["id"] for row in self.request("get", self.url).json()["results"]],
            [first.pk],
        )
        reviewer = self.request("get", self.url, user=self.ops)
        self.assertEqual(
            {row["id"] for row in reviewer.json()["results"]},
            {first.pk, second.pk},
        )
        self.assertEqual(self.request("get", self.detail_url(second)).status_code, 404)
        self.assertEqual(
            self.request(
                "get", self.detail_url(first, organization=self.other_organization)
            ).status_code,
            404,
        )
        self.assertEqual(
            self.request("get", self.url, user=self.finance).json()["results"], []
        )
        self.assertEqual(self.transition(first, "submit").status_code, 200)
        first.refresh_from_db()
        self.assertEqual(
            self.transition(
                first, "waive", user=self.ops, reason="Synthetic waiver"
            ).status_code,
            200,
        )
        first.refresh_from_db()
        self.assertEqual(
            self.transition(first, "approve", user=self.ops).status_code, 200
        )
        finance_rows = self.request("get", self.url, user=self.finance).json()[
            "results"
        ]
        self.assertEqual(len(finance_rows), 1)
        self.assertEqual(finance_rows[0]["id"], first.pk)
        self.assertNotIn("history", finance_rows[0])
        self.assertNotIn("missing_receipt_explanation", finance_rows[0])
        self.assertNotIn("claimant", finance_rows[0])
        self.assertNotIn(
            "history",
            self.request("get", self.detail_url(first), user=self.finance).json(),
        )
        self.assertEqual(
            self.request("get", self.detail_url(second), user=self.finance).status_code,
            404,
        )

    def test_return_edit_resubmit_preserves_snapshots_and_invalidates_waiver(self):
        claim = self.create()
        self.assertEqual(self.transition(claim, "submit").status_code, 200)
        claim.refresh_from_db()
        self.assertEqual(
            self.transition(
                claim, "waive", user=self.owner, reason="Accepted exception"
            ).status_code,
            200,
        )
        claim.refresh_from_db()
        self.assertEqual(
            self.transition(
                claim, "return", user=self.ops, reason="Correct the amount"
            ).status_code,
            200,
        )
        claim.refresh_from_db()
        response = self.request(
            "patch",
            self.detail_url(claim),
            {
                "revision": claim.revision,
                "amount": "99.00001",
                "purpose": "Corrected visit",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        claim.refresh_from_db()
        self.assertEqual(self.transition(claim, "resubmit").status_code, 200)
        claim.refresh_from_db()
        self.assertEqual(claim.version, 2)
        self.assertIsNone(claim.waived_version)
        self.assertEqual(
            claim.history.filter(action="submit").get().amount, Decimal("125.12345")
        )
        self.assertEqual(
            claim.history.filter(action="resubmit").get().amount, Decimal("99.00001")
        )
        self.assertEqual(
            self.transition(claim, "approve", user=self.ops).status_code, 409
        )
        self.assertEqual(
            self.transition(
                claim, "waive", user=self.ops, reason="New version reviewed"
            ).status_code,
            200,
        )
        claim.refresh_from_db()
        self.assertEqual(
            self.transition(claim, "approve", user=self.ops).status_code, 200
        )
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.APPROVED)
        self.assertIsNotNone(claim.approved_at)
        self.assertEqual(claim.history.count(), 8)

    def test_self_review_and_unreasoned_decisions_are_denied(self):
        self.assign(self.owner, self.job)
        claim = self.create(user=self.owner)
        self.assertEqual(
            self.transition(claim, "submit", user=self.owner).status_code, 200
        )
        claim.refresh_from_db()
        for action in ("return", "waive", "approve", "reject"):
            with self.subTest(action=action):
                self.assertEqual(
                    self.transition(
                        claim, action, user=self.owner, reason="Own claim"
                    ).status_code,
                    404,
                )
        for action in ("return", "waive", "reject"):
            with self.subTest(action=action):
                self.assertEqual(
                    self.transition(claim, action, user=self.ops).status_code, 400
                )
        self.assertEqual(
            self.transition(claim, "approve", user=self.ops).status_code, 409
        )
        self.assertEqual(claim.history.count(), 2)

    def test_invalid_fields_and_missing_explanation_block_submission(self):
        for changes in (
            {"expense_date": (timezone.localdate() + timedelta(days=1)).isoformat()},
            {"amount": "0"},
            {"amount": "-1"},
            {"amount": "1.000001"},
            {"amount": 1.5},
            {"currency": "kes"},
            {"currency": "US"},
            {"purpose": " "},
            {"purpose": "x"},
            {"category": "unknown"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.request("post", self.url, self.fields(**changes)).status_code,
                    400,
                )
        claim = self.create(missing_receipt_explanation="")
        self.assertEqual(self.transition(claim, "submit").status_code, 400)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.DRAFT)

    def test_finance_claimant_can_work_on_own_claim_but_cannot_review(self):
        self.assign(self.finance, self.job)
        claim = self.create(user=self.finance)
        own = self.request("get", self.detail_url(claim), user=self.finance).json()
        self.assertEqual(own["claimant"], self.finance.username)
        self.assertIn("history", own)
        self.assertEqual(
            self.transition(claim, "submit", user=self.finance).status_code, 200
        )
        claim.refresh_from_db()
        self.assertEqual(
            self.transition(
                claim, "waive", user=self.finance, reason="Cannot self-waive"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.transition(
                claim, "waive", user=self.sales, reason="No reviewer role"
            ).status_code,
            404,
        )

    def test_cancelled_job_blocks_new_claim_even_for_assignee(self):
        self.job.status = Job.Status.CANCELLED
        self.job.save(update_fields=["status"])
        self.assertEqual(self.request("post", self.url, self.fields()).status_code, 409)
        self.assertEqual(ExpenseClaim.objects.count(), 0)

    def test_unassignment_before_draft_submission_blocks_submission(self):
        claim = self.create()
        assignment = JobAssignment.objects.get(job=self.job, user=self.employee)
        assignment.unassigned_at = timezone.now()
        assignment.save(update_fields=["unassigned_at"])
        self.assertEqual(self.transition(claim, "submit").status_code, 409)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.DRAFT)
        self.assertEqual(claim.history.count(), 1)

    def test_submitted_withdrawal_preserves_submitted_snapshot(self):
        claim = self.create()
        self.assertEqual(self.transition(claim, "submit").status_code, 200)
        claim.refresh_from_db()
        self.assertEqual(self.transition(claim, "withdraw").status_code, 200)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.WITHDRAWN)
        self.assertEqual(
            list(claim.history.values_list("action", flat=True)),
            ["create", "submit", "withdraw"],
        )
        self.assertEqual(
            claim.history.filter(action="submit").get().purpose, claim.purpose
        )

    def test_unassignment_and_cancellation_do_not_erase_submitted_claim(self):
        claim = self.create()
        self.assertEqual(self.transition(claim, "submit").status_code, 200)
        assignment = JobAssignment.objects.get(job=self.job, user=self.employee)
        assignment.unassigned_at = timezone.now()
        assignment.save(update_fields=["unassigned_at"])
        self.job.status = Job.Status.CANCELLED
        self.job.save(update_fields=["status"])
        self.assertEqual(self.request("get", self.detail_url(claim)).status_code, 200)
        claim.refresh_from_db()
        self.assertEqual(
            self.transition(
                claim, "return", user=self.ops, reason="Clarify purpose"
            ).status_code,
            200,
        )
        claim.refresh_from_db()
        self.assertEqual(self.transition(claim, "resubmit").status_code, 409)
        self.assertEqual(
            self.request(
                "patch",
                self.detail_url(claim),
                {"revision": claim.revision, "purpose": "Clarified synthetic visit"},
            ).status_code,
            200,
        )
        claim.refresh_from_db()
        self.assertEqual(self.transition(claim, "resubmit").status_code, 200)
        self.assertEqual(self.request("post", self.url, self.fields()).status_code, 404)
        Membership.objects.get(
            organization=self.organization, user=self.employee
        ).delete()
        self.assertEqual(self.request("get", self.detail_url(claim)).status_code, 404)

    def test_terminal_states_and_stale_revision_conflict(self):
        claim = self.create()
        self.assertEqual(self.transition(claim, "submit").status_code, 200)
        claim.refresh_from_db()
        submitted_revision = claim.revision
        self.assertEqual(
            self.transition(
                claim, "reject", user=self.ops, reason="Not eligible"
            ).status_code,
            200,
        )
        claim.refresh_from_db()
        self.assertEqual(
            self.transition(
                claim, "approve", user=self.admin, revision=submitted_revision
            ).status_code,
            409,
        )
        self.assertEqual(self.transition(claim, "withdraw").status_code, 409)
        self.assertEqual(
            self.request(
                "patch",
                self.detail_url(claim),
                {"revision": claim.revision, "amount": "1.00000"},
            ).status_code,
            409,
        )
        self.assertEqual(claim.history.count(), 3)
        draft = self.create()
        self.assertEqual(self.transition(draft, "withdraw").status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(self.transition(draft, "submit").status_code, 409)
        self.assertEqual(ExpenseClaimHistory.objects.filter(claim=draft).count(), 2)

    def test_two_reviewers_using_the_same_revision_cannot_both_decide(self):
        claim = self.create()
        self.assertEqual(self.transition(claim, "submit").status_code, 200)
        claim.refresh_from_db()
        shared_revision = claim.revision
        self.assertEqual(
            self.transition(
                claim,
                "waive",
                user=self.ops,
                revision=shared_revision,
                reason="Synthetic waiver",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.transition(
                claim,
                "reject",
                user=self.admin,
                revision=shared_revision,
                reason="Competing review",
            ).status_code,
            409,
        )
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.SUBMITTED)
        self.assertEqual(claim.history.filter(action="reject").count(), 0)

    def test_existing_support_grant_does_not_confer_claim_access(self):
        SupportAccess.objects.create(
            user=self.support,
            organization=self.organization,
            scope=SupportAccess.Scope.DELIVERY,
            purpose="Synthetic support check",
            granted_by=self.superuser,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        claim = self.create()
        self.assertEqual(
            self.request("get", self.url, user=self.support).status_code, 404
        )
        self.assertEqual(
            self.request("get", self.detail_url(claim), user=self.support).status_code,
            404,
        )
