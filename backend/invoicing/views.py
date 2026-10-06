import json
from decimal import Decimal, localcontext
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation, QuotationLine

from .models import (
    Invoice,
    InvoiceLine,
    InvoiceSequence,
    Payment,
    PaymentAllocation,
)
from .serializers import (
    InvoiceIssueSerializer,
    InvoiceSerializer,
    InvoiceVoidSerializer,
    PaymentAllocateSerializer,
    PaymentRecordSerializer,
    PaymentSerializer,
    ReversalSerializer,
)

INVOICE_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.FINANCE,
}


def _membership(request, organization_id):
    if not request.user.is_authenticated:
        return None, JsonResponse({"detail": "Authentication required."}, status=401)
    membership = Membership.objects.filter(
        user=request.user, organization_id=organization_id
    ).first()
    if membership is None:
        return None, JsonResponse({"detail": "Organization not found."}, status=404)
    if membership.role not in INVOICE_ROLES:
        return None, JsonResponse(
            {"detail": "You do not have permission to access invoices."}, status=403
        )
    return membership, None


def _payload(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return None, JsonResponse({"detail": "A JSON object is required."}, status=400)
    return payload, None


def _validate(serializer):
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        return error.detail
    return None


def _invoice_queryset(organization_id):
    return (
        Invoice.objects.filter(organization_id=organization_id)
        .select_related(
            "customer", "job", "source_quotation", "issued_by", "voided_by", "replaces"
        )
        .prefetch_related(
            Prefetch("lines", queryset=InvoiceLine.objects.order_by("position", "id"))
        )
        .prefetch_related(
            Prefetch(
                "payment_allocations",
                queryset=PaymentAllocation.objects.select_related("payment"),
            )
        )
        .order_by("-issue_date", "invoice_number")
    )


def _payment_queryset(organization_id):
    return (
        Payment.objects.filter(organization_id=organization_id)
        .select_related("customer", "recorded_by", "reversed_by")
        .prefetch_related(
            Prefetch(
                "allocations",
                queryset=PaymentAllocation.objects.select_related(
                    "invoice", "allocated_by", "reversed_by"
                ),
            )
        )
        .order_by("-received_date", "-recorded_at")
    )


def _payment_response(payment, status=200):
    payment = _payment_queryset(payment.organization_id).get(pk=payment.pk)
    return JsonResponse(PaymentSerializer(payment).data, status=status)


def _invoice_response(invoice, status=200):
    return JsonResponse(InvoiceSerializer(invoice).data, status=status)


@require_http_methods(["GET"])
def invoices_view(request, organization_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    invoices = _invoice_queryset(organization_id)
    return JsonResponse({"results": InvoiceSerializer(invoices, many=True).data})


@require_http_methods(["GET", "POST"])
def payments_view(request, organization_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    if request.method == "GET":
        payments = _payment_queryset(organization_id)
        return JsonResponse({"results": PaymentSerializer(payments, many=True).data})

    raw_key = request.headers.get("Idempotency-Key", "")
    try:
        idempotency_key = UUID(raw_key)
    except (ValueError, TypeError):
        return JsonResponse(
            {"detail": "A valid Idempotency-Key UUID header is required."}, status=400
        )
    payload, error = _payload(request)
    if error:
        return error
    serializer = PaymentRecordSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    values = serializer.validated_data
    with transaction.atomic():
        organization = (
            Organization.objects.select_for_update().filter(pk=organization_id).first()
        )
        if organization is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        customer = Customer.objects.filter(
            organization=organization, pk=values["customer"]
        ).first()
        if customer is None:
            return JsonResponse({"detail": "Customer not found."}, status=404)
        existing = Payment.objects.filter(
            organization=organization, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            same = (
                existing.customer_id == customer.pk
                and existing.received_date == values["received_date"]
                and existing.amount == values["amount"]
                and existing.currency == values["currency"]
                and existing.method == values["method"]
                and existing.reference == values.get("reference", "")
                and existing.recorded_by_id == request.user.pk
            )
            if same:
                return _payment_response(existing)
            return JsonResponse(
                {
                    "detail": "This Idempotency-Key was already used for another payment."
                },
                status=409,
            )
        payment = Payment.objects.create(
            organization=organization,
            customer=customer,
            customer_name=customer.name,
            received_date=values["received_date"],
            amount=values["amount"],
            currency=values["currency"],
            method=values["method"],
            reference=values.get("reference", ""),
            idempotency_key=idempotency_key,
            recorded_by=request.user,
        )
    return _payment_response(payment, status=201)


@require_http_methods(["POST"])
def payment_allocate_view(request, organization_id, payment_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    payload, error = _payload(request)
    if error:
        return error
    serializer = PaymentAllocateSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    values = serializer.validated_data
    with transaction.atomic():
        organization = (
            Organization.objects.select_for_update().filter(pk=organization_id).first()
        )
        if organization is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        payment = (
            Payment.objects.select_for_update()
            .filter(organization=organization, pk=payment_id)
            .first()
        )
        if payment is None:
            return JsonResponse({"detail": "Payment not found."}, status=404)
        invoice = (
            Invoice.objects.select_for_update()
            .filter(organization=organization, pk=values["invoice"])
            .first()
        )
        if invoice is None:
            return JsonResponse({"detail": "Invoice not found."}, status=404)
        if payment.reversed_at is not None:
            return JsonResponse(
                {"detail": "A reversed payment cannot be allocated."}, status=409
            )
        if invoice.status != Invoice.Status.ISSUED:
            return JsonResponse(
                {"detail": "Only issued invoices can receive allocations."}, status=409
            )
        if payment.customer_id != invoice.customer_id:
            return JsonResponse(
                {"detail": "Payment and invoice must have the same customer."},
                status=400,
            )
        if payment.currency != invoice.currency:
            return JsonResponse(
                {"detail": "Payment and invoice currencies must match."}, status=400
            )
        payment_allocated = sum(
            PaymentAllocation.objects.filter(
                payment=payment, reversed_at__isnull=True
            ).values_list("amount", flat=True),
            Decimal("0"),
        )
        invoice_allocated = sum(
            PaymentAllocation.objects.filter(
                invoice=invoice,
                reversed_at__isnull=True,
                payment__reversed_at__isnull=True,
            ).values_list("amount", flat=True),
            Decimal("0"),
        )
        amount = values["amount"]
        if amount > payment.amount - payment_allocated:
            return JsonResponse(
                {"detail": "Allocation exceeds the unapplied payment amount."},
                status=409,
            )
        if amount > invoice.total - invoice_allocated:
            return JsonResponse(
                {"detail": "Allocation exceeds the invoice outstanding amount."},
                status=409,
            )
        PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount=amount,
            allocated_by=request.user,
        )
    return _payment_response(payment)


@require_http_methods(["POST"])
def payment_allocation_reverse_view(request, organization_id, allocation_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    payload, error = _payload(request)
    if error:
        return error
    if set(payload) != {"reason"}:
        return JsonResponse({"detail": "Provide only the reversal reason."}, status=400)
    serializer = ReversalSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    with transaction.atomic():
        organization = (
            Organization.objects.select_for_update().filter(pk=organization_id).first()
        )
        if organization is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        allocation = (
            PaymentAllocation.objects.select_for_update()
            .select_related("payment")
            .filter(payment__organization=organization, pk=allocation_id)
            .first()
        )
        if allocation is None:
            return JsonResponse({"detail": "Allocation not found."}, status=404)
        if allocation.reversed_at is not None:
            return JsonResponse(
                {"detail": "Allocation is already reversed."}, status=409
            )
        allocation.reversed_by = request.user
        allocation.reversed_at = timezone.now()
        allocation.reversal_reason = serializer.validated_data["reason"]
        allocation.save(update_fields=["reversed_by", "reversed_at", "reversal_reason"])
        payment = allocation.payment
    return _payment_response(payment)


@require_http_methods(["POST"])
def payment_reverse_view(request, organization_id, payment_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    payload, error = _payload(request)
    if error:
        return error
    if set(payload) != {"reason"}:
        return JsonResponse({"detail": "Provide only the reversal reason."}, status=400)
    serializer = ReversalSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    with transaction.atomic():
        organization = (
            Organization.objects.select_for_update().filter(pk=organization_id).first()
        )
        if organization is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        payment = (
            Payment.objects.select_for_update()
            .filter(organization=organization, pk=payment_id)
            .first()
        )
        if payment is None:
            return JsonResponse({"detail": "Payment not found."}, status=404)
        if payment.reversed_at is not None:
            return JsonResponse({"detail": "Payment is already reversed."}, status=409)
        if PaymentAllocation.objects.filter(
            payment=payment, reversed_at__isnull=True
        ).exists():
            return JsonResponse(
                {"detail": "Reverse active allocations before reversing this payment."},
                status=409,
            )
        payment.reversed_by = request.user
        payment.reversed_at = timezone.now()
        payment.reversal_reason = serializer.validated_data["reason"]
        payment.save(update_fields=["reversed_by", "reversed_at", "reversal_reason"])
    return _payment_response(payment)


@require_http_methods(["POST"])
def invoice_issue_view(request, organization_id, job_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    payload, error = _payload(request)
    if error:
        return error
    if "due_date" not in payload or set(payload) - {
        "due_date",
        "correction_reason",
        "lines",
    }:
        return JsonResponse(
            {"detail": "Provide a due_date and allowed correction fields."}, status=400
        )
    serializer = InvoiceIssueSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    try:
        with transaction.atomic():
            job = (
                Job.objects.select_related("customer", "source_quotation")
                .select_for_update()
                .filter(organization_id=organization_id, id=job_id)
                .first()
            )
            if job is None:
                return JsonResponse({"detail": "Job not found."}, status=404)
            if (
                job.status != Job.Status.COMPLETED
                or job.source_quotation.status != Quotation.Status.ACCEPTED
            ):
                return JsonResponse(
                    {
                        "detail": "Only completed jobs from accepted quotations can be invoiced."
                    },
                    status=409,
                )
            active_invoice = (
                _invoice_queryset(organization_id)
                .filter(job=job, status=Invoice.Status.ISSUED)
                .first()
            )
            if active_invoice is not None:
                return _invoice_response(active_invoice)

            quote_lines = list(
                QuotationLine.objects.filter(quotation=job.source_quotation).order_by(
                    "position", "id"
                )
            )
            if not quote_lines:
                return JsonResponse(
                    {"detail": "The accepted quotation has no invoiceable lines."},
                    status=409,
                )

            previous_invoice = (
                Invoice.objects.filter(job=job, status=Invoice.Status.VOID)
                .order_by("-issued_at", "-invoice_number")
                .first()
            )
            corrections = serializer.validated_data.get("lines")
            correction_reason = serializer.validated_data.get("correction_reason", "")
            if previous_invoice is None and (corrections or correction_reason):
                return JsonResponse(
                    {
                        "detail": "Line corrections are only allowed when replacing a void invoice."
                    },
                    status=400,
                )
            if previous_invoice is not None and not correction_reason:
                return JsonResponse(
                    {"correction_reason": ["Explain this replacement invoice."]},
                    status=400,
                )
            if corrections is not None:
                expected_positions = list(range(len(quote_lines)))
                actual_positions = [line["position"] for line in corrections]
                if actual_positions != expected_positions:
                    return JsonResponse(
                        {
                            "lines": [
                                "Provide one correction for each quotation line, in order."
                            ]
                        },
                        status=400,
                    )
                lines_by_position = {line["position"]: line for line in corrections}
                line_values = [
                    (
                        source_line,
                        lines_by_position[index]["quantity"],
                        lines_by_position[index]["unit_price"],
                    )
                    for index, source_line in enumerate(quote_lines)
                ]
            else:
                line_values = [
                    (line, line.quantity, line.unit_price) for line in quote_lines
                ]

            organization = Organization.objects.select_for_update().get(
                pk=organization_id
            )
            issue_date = timezone.localdate()
            sequence, _ = InvoiceSequence.objects.get_or_create(
                organization=organization,
                year=issue_date.year,
                defaults={"next_number": 1},
            )
            invoice_number = f"INV-{issue_date.year}-{sequence.next_number:06d}"
            sequence.next_number += 1
            sequence.save(update_fields=["next_number"])
            with localcontext() as context:
                context.prec = 40
                line_totals = [
                    (line, quantity, unit_price, quantity * unit_price)
                    for line, quantity, unit_price in line_values
                ]
                total = sum(
                    (line_total for _, _, _, line_total in line_totals), Decimal("0")
                )
            invoice = Invoice.objects.create(
                organization=organization,
                job=job,
                source_quotation=job.source_quotation,
                customer=job.customer,
                customer_name=job.customer.name,
                replaces=previous_invoice,
                invoice_number=invoice_number,
                status=Invoice.Status.ISSUED,
                issue_date=issue_date,
                due_date=serializer.validated_data["due_date"],
                currency=job.source_quotation.currency,
                total=total,
                issued_by=request.user,
                correction_reason=correction_reason,
            )
            InvoiceLine.objects.bulk_create(
                [
                    InvoiceLine(
                        invoice=invoice,
                        description=line.description,
                        quantity=quantity,
                        unit_price=unit_price,
                        line_total=line_total,
                        position=line.position,
                    )
                    for line, quantity, unit_price, line_total in line_totals
                ]
            )
    except IntegrityError:
        return JsonResponse(
            {"detail": "An invoice for this job was created concurrently."}, status=409
        )
    invoice = _invoice_queryset(organization_id).get(pk=invoice.pk)
    return _invoice_response(invoice, status=201)


@require_http_methods(["POST"])
def invoice_void_view(request, organization_id, invoice_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    payload, error = _payload(request)
    if error:
        return error
    if set(payload) != {"reason"}:
        return JsonResponse({"detail": "Provide only the void reason."}, status=400)
    serializer = InvoiceVoidSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    with transaction.atomic():
        organization = (
            Organization.objects.select_for_update().filter(pk=organization_id).first()
        )
        if organization is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        invoice = (
            Invoice.objects.select_for_update()
            .filter(organization=organization, id=invoice_id)
            .first()
        )
        if invoice is None:
            return JsonResponse({"detail": "Invoice not found."}, status=404)
        if invoice.status == Invoice.Status.ISSUED:
            if PaymentAllocation.objects.filter(
                invoice=invoice,
                reversed_at__isnull=True,
                payment__reversed_at__isnull=True,
            ).exists():
                return JsonResponse(
                    {
                        "detail": "Reverse active payment allocations before voiding this invoice."
                    },
                    status=409,
                )
            invoice.status = Invoice.Status.VOID
            invoice.void_reason = serializer.validated_data["reason"]
            invoice.voided_by = request.user
            invoice.voided_at = timezone.now()
            invoice.save(
                update_fields=["status", "void_reason", "voided_by", "voided_at"]
            )
    invoice = _invoice_queryset(organization_id).get(pk=invoice.pk)
    return _invoice_response(invoice)
