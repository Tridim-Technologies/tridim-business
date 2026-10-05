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
