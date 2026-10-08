from datetime import timedelta

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from invoicing.models import DarajaPaymentAttempt, InvoiceSequence
from quotations.models import (
    Job,
    JobStatusHistory,
    Quotation,
    QuotationLine,
    QuotationStatusHistory,
)

from .models import Membership, Organization, SupportAccess, SupportAccessAuditEvent


class TenantAdminSupportAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.operator = user_model.objects.create_superuser(
            username="platform-operator", password="a-long-test-password"
        )
        self.support = user_model.objects.create_user(
            username="support", password="a-long-test-password", is_staff=True
        )
        self.ungranted_staff = user_model.objects.create_user(
            username="ungranted", password="a-long-test-password", is_staff=True
        )
        self.customer_user = user_model.objects.create_user(
            username="tenant-user", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Alpha Services")
        self.other_organization = Organization.objects.create(name="Beta Services")
        self.grant = SupportAccess.objects.create(
            user=self.support,
            organization=self.organization,
            scope=SupportAccess.Scope.CUSTOMERS,
            purpose="Investigate reported customer directory display issue",
            granted_by=self.operator,
            expires_at=timezone.now() + timedelta(hours=2),
        )
        for scope in (
            SupportAccess.Scope.SALES,
            SupportAccess.Scope.DELIVERY,
            SupportAccess.Scope.FINANCE,
        ):
            SupportAccess.objects.create(
                user=self.support,
                organization=self.organization,
                scope=scope,
                purpose=f"Investigate {scope.label.lower()} issue",
                granted_by=self.operator,
                expires_at=timezone.now() + timedelta(hours=2),
            )
        self.customer = Customer.objects.create(
            name="Alpha Customer",
            organization=self.organization,
            created_by=self.customer_user,
        )
        self.other_customer = Customer.objects.create(
            name="Beta Customer",
            organization=self.other_organization,
            created_by=self.customer_user,
        )
        self.quotation = Quotation.objects.create(
            organization=self.organization,
            customer=self.customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=14),
            created_by=self.customer_user,
        )
        self.other_quotation = Quotation.objects.create(
            organization=self.other_organization,
            customer=self.other_customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=14),
            created_by=self.customer_user,
        )
        self.quotation_line = QuotationLine.objects.create(
            quotation=self.quotation,
            description="Synthetic support-visible service line",
            quantity=1,
            unit_price=100,
        )
        self.quotation_status_history = QuotationStatusHistory.objects.create(
            quotation=self.quotation,
            status=Quotation.Status.DRAFT,
            actor=self.customer_user,
            note="Synthetic audit note",
        )
        self.job = Job.objects.create(
            organization=self.organization,
            customer=self.customer,
            source_quotation=self.quotation,
            created_by=self.customer_user,
        )
        self.other_job = Job.objects.create(
            organization=self.other_organization,
            customer=self.other_customer,
            source_quotation=self.other_quotation,
            created_by=self.customer_user,
        )
        self.job_history = JobStatusHistory.objects.create(
            job=self.job,
            status=Job.Status.OPEN,
            actor=self.customer_user,
        )
        self.other_job_history = JobStatusHistory.objects.create(
            job=self.other_job,
            status=Job.Status.OPEN,
            actor=self.customer_user,
        )
        self.sequence = InvoiceSequence.objects.create(
            organization=self.organization, year=timezone.localdate().year
        )
        self.other_sequence = InvoiceSequence.objects.create(
            organization=self.other_organization, year=timezone.localdate().year
        )
        self.factory = RequestFactory()

    def test_staff_without_a_grant_cannot_browse_tenant_models(self):
        request = self.factory.get("/admin/")
        request.user = self.ungranted_staff

        for model in (Customer, Quotation, Job, InvoiceSequence):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertFalse(model_admin.has_module_permission(request))
                self.assertFalse(model_admin.get_queryset(request).exists())

    def test_granted_staff_querysets_and_objects_are_limited_to_the_tenant(self):
        request = self.factory.get("/admin/")
        request.user = self.support
        scoped_models = (
            (Customer, self.customer, self.other_customer),
            (Quotation, self.quotation, self.other_quotation),
            (Job, self.job, self.other_job),
            (JobStatusHistory, self.job_history, self.other_job_history),
            (InvoiceSequence, self.sequence, self.other_sequence),
        )

        for model, allowed, denied in scoped_models:
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                queryset = model_admin.get_queryset(request)
                self.assertTrue(queryset.filter(pk=allowed.pk).exists())
                self.assertFalse(queryset.filter(pk=denied.pk).exists())
                self.assertTrue(model_admin.has_view_permission(request, allowed))
                self.assertFalse(model_admin.has_view_permission(request, denied))
                self.assertFalse(model_admin.has_change_permission(request, allowed))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))

    def test_tenant_staff_cannot_open_global_admin_modules(self):
        request = self.factory.get("/admin/")
        request.user = self.support
        for model in (Organization, Membership, get_user_model()):
            with self.subTest(model=model.__name__):
                self.assertFalse(
                    admin.site._registry[model].has_module_permission(request)
                )

    def test_grant_only_exposes_its_named_data_scope(self):
        finance_support = get_user_model().objects.create_user(
            username="finance-support",
            password="a-long-test-password",
            is_staff=True,
        )
        SupportAccess.objects.create(
            user=finance_support,
            organization=self.organization,
            scope=SupportAccess.Scope.FINANCE,
            purpose="Investigate a finance page issue",
            granted_by=self.operator,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        request = self.factory.get("/admin/")
        request.user = finance_support

        self.assertTrue(
            admin.site._registry[InvoiceSequence].has_module_permission(request)
        )
        self.assertFalse(admin.site._registry[Customer].has_module_permission(request))
        self.assertFalse(admin.site._registry[Quotation].has_module_permission(request))

    def test_payment_diagnostics_hide_phone_and_raw_provider_response(self):
        request = self.factory.get("/admin/")
        request.user = self.support
        fields = admin.site._registry[DarajaPaymentAttempt].get_fields(request)
        self.assertNotIn("phone_number", fields)
        self.assertNotIn("response_data", fields)

    def test_quotation_lines_and_history_are_read_only_under_scoped_parent(self):
        self.client.force_login(self.support)
        response = self.client.get(
            reverse("admin:quotations_quotation_change", args=[self.quotation.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Synthetic support-visible service line")
        self.assertContains(response, "Synthetic audit note")

    def test_read_only_admin_list_and_object_views_are_audited(self):
        self.client.force_login(self.support)
        list_response = self.client.get(reverse("admin:customers_customer_changelist"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Alpha Customer")
        self.assertNotContains(list_response, "Beta Customer")

        allowed_response = self.client.get(
            reverse("admin:customers_customer_change", args=[self.customer.pk])
        )
        self.assertEqual(allowed_response.status_code, 200)
        denied_write_response = self.client.post(
            reverse("admin:customers_customer_change", args=[self.customer.pk]),
            {"name": "Tampered Customer"},
        )
        self.assertEqual(denied_write_response.status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "Alpha Customer")
        denied_response = self.client.get(
            reverse("admin:customers_customer_change", args=[self.other_customer.pk])
        )
        self.assertIn(denied_response.status_code, (302, 404))
        self.assertNotIn(
            str(self.other_customer.pk), denied_response.get("Location", "")
        )
        self.assertEqual(
            SupportAccessAuditEvent.objects.filter(
                support_access=self.grant,
                model_label="customers.customer",
            ).count(),
            2,
        )

    def test_object_view_audit_is_attributed_to_the_matching_tenant_grant(self):
        other_grant = SupportAccess.objects.create(
            user=self.support,
            organization=self.other_organization,
            scope=SupportAccess.Scope.CUSTOMERS,
            purpose="Investigate a separate customer issue",
            granted_by=self.operator,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.client.force_login(self.support)
        response = self.client.get(
            reverse("admin:customers_customer_change", args=[self.other_customer.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            SupportAccessAuditEvent.objects.filter(
                support_access=other_grant,
                model_label="customers.customer",
                object_pk=str(self.other_customer.pk),
                access_type=SupportAccessAuditEvent.AccessType.OBJECT,
            ).exists()
        )
        self.assertFalse(
            SupportAccessAuditEvent.objects.filter(
                support_access=self.grant,
                model_label="customers.customer",
                object_pk=str(self.other_customer.pk),
            ).exists()
        )

    def test_expired_or_revoked_grants_do_not_authorize_access(self):
        expired_user = get_user_model().objects.create_user(
            username="expired-support", password="a-long-test-password", is_staff=True
        )
        now = timezone.now()
        SupportAccess.objects.create(
            user=expired_user,
            organization=self.organization,
            scope=SupportAccess.Scope.CUSTOMERS,
            purpose="Expired access test",
            granted_by=self.operator,
            granted_at=now - timedelta(hours=3),
            expires_at=now - timedelta(hours=1),
        )
        revoked_user = get_user_model().objects.create_user(
            username="revoked-support", password="a-long-test-password", is_staff=True
        )
        SupportAccess.objects.create(
            user=revoked_user,
            organization=self.organization,
            scope=SupportAccess.Scope.CUSTOMERS,
            purpose="Revoked access test",
            granted_by=self.operator,
            expires_at=now + timedelta(hours=2),
            revoked_at=now,
        )

        for user in (expired_user, revoked_user):
            request = self.factory.get("/admin/")
            request.user = user
            model_admin = admin.site._registry[Customer]
            with self.subTest(user=user.username):
                self.assertFalse(model_admin.has_module_permission(request))
                self.assertFalse(model_admin.get_queryset(request).exists())

    def test_grant_requires_active_staff_and_an_eight_hour_maximum(self):
        invalid = SupportAccess(
            user=self.ungranted_staff,
            organization=self.organization,
            scope=SupportAccess.Scope.CUSTOMERS,
            purpose="Test expiry cap",
            granted_by=self.operator,
            expires_at=timezone.now() + timedelta(hours=9),
        )
        with self.assertRaises(ValidationError):
            invalid.save()

        tenant_user_grant = SupportAccess(
            user=self.customer_user,
            organization=self.organization,
            scope=SupportAccess.Scope.CUSTOMERS,
            purpose="Test staff restriction",
            granted_by=self.operator,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        with self.assertRaises(ValidationError):
            tenant_user_grant.save()

    def test_superuser_can_revoke_a_grant_and_the_action_is_logged(self):
        self.client.force_login(self.operator)
        response = self.client.post(
            reverse("admin:accounts_supportaccess_changelist"),
            {"action": "revoke_access", "_selected_action": [str(self.grant.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertTrue(
            LogEntry.objects.filter(
                object_id=str(self.grant.pk), change_message="Support access revoked"
            ).exists()
        )
