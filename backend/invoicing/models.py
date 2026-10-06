import uuid

from django.conf import settings
from django.db import models

from accounts.models import Organization
from customers.models import Customer
from quotations.models import Job, Quotation


class InvoiceSequence(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoice_sequences"
    )
    year = models.PositiveSmallIntegerField()
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year"], name="unique_invoice_sequence_year"
            )
        ]


class Invoice(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        VOID = "void", "Void"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoices"
    )
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="invoices")
    source_quotation = models.ForeignKey(
        Quotation, on_delete=models.PROTECT, related_name="invoices"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="invoices"
    )
    customer_name = models.CharField(max_length=200)
    replaces = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="replacements",
        null=True,
        blank=True,
    )
    invoice_number = models.CharField(max_length=24)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.ISSUED
    )
    issue_date = models.DateField()
    due_date = models.DateField()
    currency = models.CharField(max_length=3)
    total = models.DecimalField(max_digits=30, decimal_places=5)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_invoices",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    correction_reason = models.CharField(max_length=240, blank=True)
    void_reason = models.CharField(max_length=240, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="voided_invoices",
        null=True,
        blank=True,
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issue_date", "invoice_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "invoice_number"],
                name="unique_invoice_number_per_org",
            ),
            models.UniqueConstraint(
                fields=["job"],
                condition=models.Q(status="issued"),
                name="unique_active_invoice_per_job",
            ),
        ]

    def __str__(self):
        return self.invoice_number


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    description = models.CharField(max_length=240)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=24, decimal_places=5)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "position"], name="unique_invoice_line_position"
            )
        ]


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CARD = "card", "Card"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        CHEQUE = "cheque", "Cheque"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="payments"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="payments"
    )
    customer_name = models.CharField(max_length=200)
    received_date = models.DateField()
    amount = models.DecimalField(max_digits=30, decimal_places=5)
    currency = models.CharField(max_length=3)
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=120, blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_payments",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reversed_payments",
        null=True,
        blank=True,
    )
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-received_date", "-recorded_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payment_amount_positive"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_payment_idempotency_per_org",
            ),
        ]


class PaymentAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="allocations"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payment_allocations"
    )
    amount = models.DecimalField(max_digits=30, decimal_places=5)
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_allocations",
    )
    allocated_at = models.DateTimeField(auto_now_add=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reversed_payment_allocations",
        null=True,
        blank=True,
    )
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["allocated_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="payment_allocation_amount_positive",
            )
        ]


class DarajaPaymentAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REVIEW = "review", "Needs review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="daraja_payment_attempts"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="daraja_payment_attempts"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="daraja_payment_attempts"
    )
    amount = models.DecimalField(max_digits=30, decimal_places=5)
    phone_number = models.CharField(max_length=12)
    idempotency_key = models.UUIDField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    checkout_request_id = models.CharField(max_length=120, unique=True, null=True)
    merchant_request_id = models.CharField(max_length=120, blank=True)
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="daraja_attempt",
        null=True,
        blank=True,
    )
    result_code = models.CharField(max_length=40, blank=True)
    result_description = models.CharField(max_length=240, blank=True)
    response_data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="daraja_payment_attempts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_daraja_attempt_idempotency_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="daraja_attempt_amount_positive"
            ),
        ]


class DarajaCallbackEvent(models.Model):
    attempt = models.ForeignKey(
        DarajaPaymentAttempt,
        on_delete=models.PROTECT,
        related_name="callback_events",
        null=True,
        blank=True,
    )
    checkout_request_id = models.CharField(max_length=120, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    delivery_count = models.PositiveIntegerField(default=1)
    received_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
