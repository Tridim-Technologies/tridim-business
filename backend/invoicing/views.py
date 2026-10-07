import csv
import json
from datetime import UTC
from decimal import Decimal, localcontext
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models import Prefetch
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
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
    DarajaCallbackEvent,
    DarajaPaymentAttempt,
)
from .serializers import (
    InvoiceIssueSerializer,
    InvoiceSerializer,
    InvoiceVoidSerializer,
    PaymentAllocateSerializer,
    PaymentRecordSerializer,
    PaymentSerializer,
    ReversalSerializer,
    DarajaPaymentAttemptCreateSerializer,
    DarajaPaymentAttemptSerializer,
)
from .daraja import (
    DarajaUnavailable,
    amount_for_attempt,
    callback_matches_success,
    initiate_stk_push,
    is_final_query,
    is_successful_query,
    normalize_phone_number,
    phone_number_digest,
    query_matches_attempt,
    query_stk_push,
    is_configured as daraja_is_configured,
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


def _link_daraja_attempt_payment(payment):
    if payment.method != Payment.Method.MOBILE_MONEY or not payment.reference:
        return
    attempt = (
        DarajaPaymentAttempt.objects.select_for_update()
        .filter(
            organization=payment.organization,
            customer=payment.customer,
            amount=payment.amount,
            checkout_request_id=payment.reference,
            status=DarajaPaymentAttempt.Status.SUCCEEDED,
            payment__isnull=True,
            invoice__currency=payment.currency,
        )
        .first()
    )
    if attempt:
        attempt.payment = payment
        attempt.save(update_fields=["payment", "updated_at"])


def _invoice_response(invoice, status=200):
    return JsonResponse(InvoiceSerializer(invoice).data, status=status)


@require_http_methods(["GET"])
def invoices_view(request, organization_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    invoices = _invoice_queryset(organization_id)
    return JsonResponse({"results": InvoiceSerializer(invoices, many=True).data})


class _CsvBuffer:
    def write(self, value):
        return value


def _csv_text(value):
    if not isinstance(value, str):
        return value
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv_decimal(value):
    return format(value, ".5f")


def _csv_timestamp(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _csv_response(filename, headers, rows, as_of, definitions):
    def stream():
        buffer = _CsvBuffer()
        writer = csv.writer(buffer, lineterminator="\r\n")
        yield "\ufeff"
        yield writer.writerow(["# export_as_of_utc", as_of])
        yield writer.writerow(["# definitions", definitions])
        yield writer.writerow([*headers, "export_as_of_utc"])
        for row in rows:
            yield writer.writerow([*row, as_of])

    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Export-As-Of-UTC"] = as_of
    return response


@require_http_methods(["GET"])
def finance_export_view(request, organization_id, resource):
    _, error = _membership(request, organization_id)
    if error:
        return error
    as_of = _csv_timestamp(timezone.now())
    if resource == "invoices":

        def invoice_rows():
            for invoice in _invoice_queryset(organization_id).iterator(chunk_size=500):
                allocated = sum(
                    (
                        allocation.amount
                        for allocation in invoice.payment_allocations.all()
                        if allocation.reversed_at is None
                        and allocation.payment.reversed_at is None
                    ),
                    Decimal("0.00000"),
                )
                outstanding = (
                    invoice.total - allocated
                    if invoice.status == Invoice.Status.ISSUED
                    else ""
                )
                state = (
                    "void"
                    if invoice.status == Invoice.Status.VOID
                    else (
                        "paid"
                        if outstanding == 0
                        else "partial"
                        if allocated > 0
                        else "unpaid"
                    )
                )
                yield (
                    str(invoice.id),
                    _csv_text(invoice.invoice_number),
                    invoice.customer_id,
                    _csv_text(invoice.customer_name),
                    invoice.job_id,
                    invoice.status,
                    invoice.issue_date.isoformat(),
                    invoice.due_date.isoformat(),
                    invoice.currency,
                    _csv_decimal(invoice.total),
                    _csv_decimal(allocated),
                    _csv_decimal(outstanding) if outstanding != "" else "",
                    state,
                    _csv_text(invoice.issued_by.get_username()),
                    _csv_timestamp(invoice.issued_at),
                    _csv_text(invoice.void_reason),
                    _csv_text(invoice.voided_by.get_username())
                    if invoice.voided_by
                    else "",
                    _csv_timestamp(invoice.voided_at) if invoice.voided_at else "",
                )

        return _csv_response(
            "invoices.csv",
            (
                "invoice_id",
                "invoice_number",
                "customer_id",
                "customer_name",
                "job_id",
                "invoice_status",
                "issue_date",
                "due_date",
                "currency",
                "issued_total",
                "allocated_total",
                "outstanding_total",
                "payment_state",
                "issued_by",
                "issued_at_utc",
                "void_reason",
                "voided_by",
                "voided_at_utc",
            ),
            invoice_rows(),
            as_of,
            "issued_total is the recorded invoice total; allocated_total sums active allocations; "
            "outstanding_total is issued_total minus active allocations for issued invoices only. "
            "Voided invoices have no outstanding balance.",
        )
    if resource == "payments":

        def payment_rows():
            for payment in _payment_queryset(organization_id).iterator(chunk_size=500):
                allocations = [
                    allocation
                    for allocation in payment.allocations.all()
                    if allocation.reversed_at is None
                ]
                allocated = (
                    sum((item.amount for item in allocations), Decimal("0.00000"))
                    if payment.reversed_at is None
                    else Decimal("0.00000")
                )
                unapplied = (
                    payment.amount - allocated
                    if payment.reversed_at is None
                    else Decimal("0.00000")
                )
                state = (
                    "reversed"
                    if payment.reversed_at
                    else "unapplied"
                    if allocated == 0
                    else "applied"
                    if unapplied == 0
                    else "partially_applied"
                )
                yield (
                    str(payment.id),
                    payment.customer_id,
                    _csv_text(payment.customer_name),
                    payment.received_date.isoformat(),
                    _csv_decimal(payment.amount),
                    payment.currency,
                    payment.method,
                    _csv_text(payment.reference),
                    state,
                    _csv_decimal(allocated),
                    _csv_decimal(unapplied),
                    _csv_text(payment.recorded_by.get_username()),
                    _csv_timestamp(payment.recorded_at),
                    _csv_text(payment.reversal_reason),
                    _csv_text(payment.reversed_by.get_username())
                    if payment.reversed_by
                    else "",
                    _csv_timestamp(payment.reversed_at) if payment.reversed_at else "",
                )

        return _csv_response(
            "payments.csv",
            (
                "payment_id",
                "customer_id",
                "customer_name",
                "received_date",
                "amount",
                "currency",
                "method",
                "reference",
                "payment_state",
                "allocated_total",
                "unapplied_total",
                "recorded_by",
                "recorded_at_utc",
                "reversal_reason",
                "reversed_by",
                "reversed_at_utc",
            ),
            payment_rows(),
            as_of,
            "allocated_total sums active allocations unless the payment is reversed; unapplied_total "
            "is amount minus allocated_total for active receipts and zero for reversed receipts. "
            "payment_state distinguishes unapplied, partially_applied, applied, and reversed.",
        )
    if resource == "allocations":

        def allocation_rows():
            allocations = (
                PaymentAllocation.objects.filter(
                    payment__organization_id=organization_id
                )
                .select_related(
                    "payment",
                    "payment__customer",
                    "payment__reversed_by",
                    "invoice",
                    "allocated_by",
                    "reversed_by",
                )
                .order_by("allocated_at", "id")
            )
            for allocation in allocations.iterator(chunk_size=500):
                yield (
                    str(allocation.id),
                    str(allocation.payment_id),
                    str(allocation.invoice_id),
                    _csv_text(allocation.invoice.invoice_number),
                    allocation.payment.customer_id,
                    _csv_text(allocation.payment.customer_name),
                    _csv_decimal(allocation.amount),
                    allocation.payment.currency,
                    _csv_text(allocation.allocated_by.get_username()),
                    _csv_timestamp(allocation.allocated_at),
                    "reversed" if allocation.reversed_at else "active",
                    _csv_text(allocation.reversal_reason),
                    _csv_text(allocation.reversed_by.get_username())
                    if allocation.reversed_by
                    else "",
                    _csv_timestamp(allocation.reversed_at)
                    if allocation.reversed_at
                    else "",
                    "reversed" if allocation.payment.reversed_at else "active",
                )

        return _csv_response(
            "payment-allocations.csv",
            (
                "allocation_id",
                "payment_id",
                "invoice_id",
                "invoice_number",
                "customer_id",
                "customer_name",
                "amount",
                "currency",
                "allocated_by",
                "allocated_at_utc",
                "allocation_state",
                "reversal_reason",
                "reversed_by",
                "reversed_at_utc",
                "payment_state",
            ),
            allocation_rows(),
            as_of,
            "Every allocation is retained; allocation_state indicates active or reversed, and "
            "payment_state independently indicates whether its receipt is active or reversed.",
        )
    return JsonResponse({"detail": "Unknown finance export."}, status=404)


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
                _link_daraja_attempt_payment(existing)
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
        _link_daraja_attempt_payment(payment)
    return _payment_response(payment, status=201)


def _daraja_attempt_response(attempt, status=200):
    return JsonResponse(DarajaPaymentAttemptSerializer(attempt).data, status=status)


def _invoice_active_allocated(invoice):
    return sum(
        PaymentAllocation.objects.filter(
            invoice=invoice,
            reversed_at__isnull=True,
            payment__reversed_at__isnull=True,
        ).values_list("amount", flat=True),
        Decimal("0.00000"),
    )


def _invoice_active_attempt_reservations(invoice):
    reserved = Decimal("0.00000")
    statuses = (
        DarajaPaymentAttempt.Status.PENDING,
        DarajaPaymentAttempt.Status.REVIEW,
        DarajaPaymentAttempt.Status.SUCCEEDED,
    )
    attempts = DarajaPaymentAttempt.objects.filter(
        invoice=invoice, status__in=statuses
    ).select_for_update()
    for attempt in attempts:
        if (
            attempt.status == DarajaPaymentAttempt.Status.SUCCEEDED
            and attempt.payment_id
        ):
            if PaymentAllocation.objects.filter(
                payment_id=attempt.payment_id, reversed_at__isnull=True
            ).exists():
                continue
        reserved += attempt.amount
    return reserved


@require_http_methods(["POST"])
def daraja_payment_attempt_create_view(request, organization_id, invoice_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    if not daraja_is_configured():
        return JsonResponse(
            {"detail": "Daraja sandbox payments are not configured."}, status=503
        )
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
    serializer = DarajaPaymentAttemptCreateSerializer(data=payload)
    errors = _validate(serializer)
    if errors:
        return JsonResponse(errors, status=400)
    values = serializer.validated_data
    try:
        amount = amount_for_attempt(values["amount"])
        phone_number = normalize_phone_number(values["phone_number"])
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    with transaction.atomic():
        organization = (
            Organization.objects.select_for_update().filter(pk=organization_id).first()
        )
        if organization is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        existing = DarajaPaymentAttempt.objects.filter(
            organization=organization, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            same = (
                existing.invoice_id == invoice_id
                and existing.amount == amount
                and existing.phone_number == phone_number
                and existing.created_by_id == request.user.pk
            )
            if same:
                return _daraja_attempt_response(existing, status=202)
            return JsonResponse(
                {
                    "detail": "This Idempotency-Key was already used for another attempt."
                },
                status=409,
            )
        invoice = (
            Invoice.objects.select_for_update()
            .select_related("customer")
            .filter(organization=organization, pk=invoice_id)
            .first()
        )
        if invoice is None:
            return JsonResponse({"detail": "Invoice not found."}, status=404)
        if invoice.status != Invoice.Status.ISSUED:
            return JsonResponse(
                {"detail": "Only issued invoices can receive M-Pesa prompts."},
                status=409,
            )
        if invoice.currency != "KES":
            return JsonResponse(
                {"detail": "M-Pesa Express attempts require a KES invoice."}, status=400
            )
        available = (
            invoice.total
            - _invoice_active_allocated(invoice)
            - _invoice_active_attempt_reservations(invoice)
        )
        if available <= 0 or amount > available:
            return JsonResponse(
                {"detail": "The amount exceeds the invoice's available balance."},
                status=409,
            )
        attempt = DarajaPaymentAttempt.objects.create(
            organization=organization,
            invoice=invoice,
            customer=invoice.customer,
            amount=amount,
            phone_number=phone_number,
            idempotency_key=idempotency_key,
            created_by=request.user,
        )

    try:
        response = initiate_stk_push(attempt)
    except DarajaUnavailable:
        attempt.status = DarajaPaymentAttempt.Status.REVIEW
        attempt.result_description = "Sandbox credentials are unavailable."
        attempt.save(update_fields=["status", "result_description", "updated_at"])
        return _daraja_attempt_response(attempt, status=202)
    except Exception:
        # A transport failure can happen after Daraja accepted the prompt. Keep
        # the amount reserved; do not automatically issue another prompt.
        attempt.status = DarajaPaymentAttempt.Status.REVIEW
        attempt.result_description = (
            "The request outcome is unknown. Review this attempt before retrying."
        )
        attempt.save(update_fields=["status", "result_description", "updated_at"])
        return _daraja_attempt_response(attempt, status=202)

    attempt.checkout_request_id = response["CheckoutRequestID"]
    attempt.merchant_request_id = str(response.get("MerchantRequestID", ""))[:120]
    attempt.response_data = response
    attempt.save(
        update_fields=[
            "checkout_request_id",
            "merchant_request_id",
            "response_data",
            "updated_at",
        ]
    )
    early_event = DarajaCallbackEvent.objects.filter(
        checkout_request_id=attempt.checkout_request_id, attempt__isnull=True
    ).first()
    if early_event is not None:
        early_event.attempt = attempt
        early_event.save(update_fields=["attempt"])
        _process_daraja_callback_event(early_event)
        attempt.refresh_from_db()
    return _daraja_attempt_response(attempt, status=202)


@require_http_methods(["GET"])
def daraja_payment_attempt_view(request, organization_id, attempt_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    attempt = DarajaPaymentAttempt.objects.filter(
        organization_id=organization_id, pk=attempt_id
    ).first()
    if attempt is None:
        return JsonResponse({"detail": "Payment attempt not found."}, status=404)
    return _daraja_attempt_response(attempt)


@require_http_methods(["POST"])
def daraja_payment_attempt_reconcile_view(request, organization_id, attempt_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    attempt = DarajaPaymentAttempt.objects.filter(
        organization_id=organization_id, pk=attempt_id
    ).first()
    if attempt is None:
        return JsonResponse({"detail": "Payment attempt not found."}, status=404)
    if not attempt.checkout_request_id:
        return JsonResponse(
            {"detail": "This attempt has no checkout identifier to query."}, status=409
        )
    event = DarajaCallbackEvent.objects.filter(attempt=attempt).first()
    if event is None:
        return JsonResponse(
            {"detail": "No callback has been received for this attempt."}, status=409
        )
    _process_daraja_callback_event(event)
    attempt.refresh_from_db()
    status = (
        200
        if attempt.status
        in (DarajaPaymentAttempt.Status.SUCCEEDED, DarajaPaymentAttempt.Status.FAILED)
        else 202
    )
    return _daraja_attempt_response(attempt, status=status)


def _callback_ack():
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


def _process_daraja_callback_event(event):
    attempt = event.attempt
    if attempt is None or attempt.status in (
        DarajaPaymentAttempt.Status.SUCCEEDED,
        DarajaPaymentAttempt.Status.FAILED,
    ):
        return
    try:
        verified = query_stk_push(event.checkout_request_id)
    except Exception:
        return
    with transaction.atomic():
        attempt = (
            DarajaPaymentAttempt.objects.select_for_update()
            .filter(pk=attempt.pk)
            .first()
        )
        if attempt is None or attempt.status in (
            DarajaPaymentAttempt.Status.SUCCEEDED,
            DarajaPaymentAttempt.Status.FAILED,
        ):
            return

        # Require Daraja to echo both provider request identifiers. If the
        # query response omits either identifier, require manual review.
        if not query_matches_attempt(verified, attempt):
            attempt.status = DarajaPaymentAttempt.Status.REVIEW
            attempt.result_description = (
                "The status response did not match this attempt."
            )
            attempt.save(update_fields=["status", "result_description", "updated_at"])
            return
        if not is_final_query(verified):
            return

        result_code = str(verified.get("ResultCode", ""))
        callback = event.payload
        if result_code == "0":
            if not callback_matches_success(callback, attempt, verified):
                attempt.status = DarajaPaymentAttempt.Status.REVIEW
                attempt.result_description = "The verified checkout did not match callback amount or phone details."
                attempt.save(
                    update_fields=["status", "result_description", "updated_at"]
                )
                return
        elif str(callback.get("ResultCode", "")) != result_code:
            attempt.status = DarajaPaymentAttempt.Status.REVIEW
            attempt.result_description = "The callback and status result did not match."
            attempt.save(update_fields=["status", "result_description", "updated_at"])
            return

        attempt.result_code = result_code[:40]
        attempt.result_description = str(verified.get("ResultDesc", ""))[:240]
        attempt.response_data = verified
        attempt.status = (
            DarajaPaymentAttempt.Status.SUCCEEDED
            if is_successful_query(verified)
            else DarajaPaymentAttempt.Status.FAILED
        )
        attempt.save(
            update_fields=[
                "result_code",
                "result_description",
                "response_data",
                "status",
                "updated_at",
            ]
        )
        DarajaCallbackEvent.objects.filter(pk=event.pk).update(
            attempt=attempt, processed_at=timezone.now()
        )


@csrf_exempt
@require_http_methods(["POST"])
def daraja_stk_callback_view(request):
    if not daraja_is_configured():
        return _callback_ack()
    payload, error = _payload(request)
    if error:
        return _callback_ack()
    body = payload.get("Body")
    callback = body.get("stkCallback") if isinstance(body, dict) else None
    if not isinstance(callback, dict):
        return _callback_ack()
    checkout_request_id = callback.get("CheckoutRequestID")
    if not isinstance(checkout_request_id, str) or not checkout_request_id.strip():
        return _callback_ack()
    checkout_request_id = checkout_request_id[:120]
    callback_metadata = callback.get("CallbackMetadata")
    items = (
        callback_metadata.get("Item") if isinstance(callback_metadata, dict) else None
    )
    if not isinstance(items, list):
        items = []
    item_map = {
        item.get("Name"): item.get("Value")
        for item in items
        if isinstance(items, list)
        and isinstance(item, dict)
        and isinstance(item.get("Name"), str)
    }
    safe_payload = {
        "CheckoutRequestID": checkout_request_id,
        "MerchantRequestID": str(callback.get("MerchantRequestID", ""))[:120],
        "ResultCode": str(callback.get("ResultCode", ""))[:40],
        "ResultDesc": str(callback.get("ResultDesc", ""))[:240],
        "CallbackMetadata": {
            "Item": [
                {"Name": "Amount", "Value": item_map.get("Amount")},
                {
                    "Name": "PhoneNumberHash",
                    "Value": phone_number_digest(item_map.get("PhoneNumber")),
                },
            ]
        },
    }
    attempt = DarajaPaymentAttempt.objects.filter(
        checkout_request_id=checkout_request_id
    ).first()
    event, created = DarajaCallbackEvent.objects.get_or_create(
        checkout_request_id=checkout_request_id,
        defaults={"attempt": attempt, "payload": safe_payload},
    )
    if not created:
        updates = {
            "delivery_count": F("delivery_count") + 1,
            "last_received_at": timezone.now(),
        }
        if event.attempt_id is None and attempt is not None:
            updates["attempt"] = attempt
        DarajaCallbackEvent.objects.filter(pk=event.pk).update(**updates)
        event.refresh_from_db()
    _process_daraja_callback_event(event)
    return _callback_ack()


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
