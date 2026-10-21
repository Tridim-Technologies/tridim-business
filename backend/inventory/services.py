from decimal import Decimal

from django.db.models import BigIntegerField, Case, F, Q, Sum, When

from .models import StockMovement


def location_stock_balances(organization_id):
    movements = StockMovement.objects.filter(organization_id=organization_id)
    by_source = (
        movements.filter(
            Q(kind=StockMovement.Kind.ISSUE)
            | Q(
                kind=StockMovement.Kind.ADJUSTMENT,
                direction=StockMovement.Direction.DECREASE,
            )
            | Q(kind=StockMovement.Kind.TRANSFER)
        )
        .values("product_id", "location_id")
        .annotate(total=Sum("quantity"))
    )
    by_destination = (
        movements.filter(
            Q(kind=StockMovement.Kind.RECEIPT)
            | Q(
                kind=StockMovement.Kind.ADJUSTMENT,
                direction=StockMovement.Direction.INCREASE,
            )
            | Q(kind=StockMovement.Kind.TRANSFER)
        )
        .annotate(
            balance_location_id=Case(
                When(kind=StockMovement.Kind.TRANSFER, then=F("destination_id")),
                default=F("location_id"),
                output_field=BigIntegerField(),
            )
        )
        .values("product_id", "balance_location_id")
        .annotate(total=Sum("quantity"))
    )
    totals = {}
    for row in by_destination:
        totals[(row["product_id"], row["balance_location_id"])] = row["total"]
    for row in by_source:
        key = (row["product_id"], row["location_id"])
        totals[key] = totals.get(key, Decimal("0")) - row["total"]
    return totals


def product_stock_totals(organization_id):
    totals = {}
    for (product_id, _location_id), quantity in location_stock_balances(
        organization_id
    ).items():
        totals[product_id] = totals.get(product_id, Decimal("0")) + quantity
    return totals
