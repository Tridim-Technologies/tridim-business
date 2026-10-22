# Inventory in the synthetic alpha

**Status:** Local product, stock availability, and job reservation tracking; no costing or accounting integration

The inventory screen provides an organization-scoped catalog, stock locations, on-hand quantities, and a recent movement history. The current increment is intended for synthetic data while the core workflow is being built.

## Catalog and locations

- A product has an organization-unique SKU, name, base unit, and active state. SKU matching is case-insensitive within an organization.
- A product can have a non-negative reorder point in its base unit. The default `0.000` disables reorder tracking. A positive threshold is compared with the total on-hand quantity across all locations; it does not trigger an automatic purchase.
- A location has an organization-unique code, name, and active state.
- Products and locations are never hard-deleted after movement history references them.
- Product and location codes do not imply a country-specific numbering, unit conversion, or currency convention.

## Stock movements

Each movement is immutable and records the product, quantity, actor, time, reason, organization, and request idempotency key.

| Movement | Quantity effect |
|---|---|
| Receipt | Adds quantity at one location |
| Issue | Removes quantity at one location |
| Adjustment increase or decrease | Applies a reasoned counted-stock correction at one location |
| Transfer | Removes quantity from one location and adds the same amount to another atomically |

Quantities use decimal precision of three places. Receipts and increases establish stock; issues, decreases, and transfers are rejected if they would produce a negative quantity. Repeating a request with the same organization-scoped idempotency key and same payload returns the original movement. Reusing the key for different movement data returns a conflict.

On-hand quantities are calculated from movement history and returned per location and as an organization-wide total. Active job reservations reduce available stock without changing on-hand quantity. Available quantity is `on hand - active reservations` for each product and location. Direct issues, adjustment decreases, and transfers are rejected when they would consume a reserved quantity. Receipts increase on-hand and therefore available stock. Products below a positive reorder point appear in the low-stock view. Corrections are new compensating movements; existing events are not edited or deleted through the API.

## Reserve materials for a job

Owners, administrators, and operations members can create a location-specific reservation for active products on a job in the same organization. Reservation quantities use exact decimal strings with three places. The server checks and records the request atomically under the same organization lock used by stock movements, so concurrent reservations cannot allocate the same available units twice.

Reservations are immutable after creation. If a plan changes, explicitly release its unused quantities and create a replacement reservation; prior reservation records remain visible. A material issue can reference one or more active reservation lines for that job. Partial use reduces the line's remaining reserved quantity and creates the ordinary immutable issue movement. Issues without a reservation reference can use only unreserved available stock. Releasing a reservation does not change on-hand quantity.

## Issue materials to a job

Owners, administrators, and operations members can record one or more product quantities from active locations against an organization job. Each request has a reason and organization-scoped UUID idempotency key. An accepted request atomically creates an immutable job issue and linked stock issue movements; insufficient stock, inactive or cross-organization products/locations, and a mismatched retry are rejected. The job delivery history shows the recorded materials, and inventory movement history identifies the job.

This records consumption after it occurs. It does not reserve stock, allocate material cost, value inventory, or create invoice or accounting entries.

## Access

- Owners, administrators, and operations members can create and update products, create locations, and record stock movements.
- Owners, administrators, and operations members can create and release job material reservations and issue reserved materials.
- Owners, administrators, operations, sales, and finance members can view inventory.
- Other roles cannot read the inventory API.
- Every API query scopes products, locations, movements, and identifiers to the selected organization.

## API

| Route | Methods | Purpose |
|---|---|---|
| `/api/organizations/{organization_id}/inventory/` | GET | Products with `reorder_point`, aggregate `on_hand_quantity`, per-location balances, locations, and the latest 100 movements |
| `/api/organizations/{organization_id}/inventory/products/` | POST | Create a product |
| `/api/organizations/{organization_id}/inventory/products/{product_id}/` | PATCH | Update product catalog fields |
| `/api/organizations/{organization_id}/inventory/locations/` | POST | Create a location |
| `/api/organizations/{organization_id}/inventory/locations/{location_id}/` | PATCH | Update a location; deactivation requires zero stock |
| `/api/organizations/{organization_id}/inventory/movements/` | GET, POST | List recent movements or record one movement |
| `/api/organizations/{organization_id}/jobs/{job_id}/material-issues/` | POST | Record quantity-only stock issue lines against a job |
| `/api/organizations/{organization_id}/jobs/{job_id}/material-reservations/` | GET, POST | Read job reservations or reserve available product quantities by location |
| `/api/organizations/{organization_id}/jobs/{job_id}/material-reservations/{reservation_id}/release/` | POST | Release an active reservation's unused quantities |

Product create/update requests can include `reorder_point` as a non-negative decimal string. Movement requests include `product_id`, `kind`, `location_id`, a positive decimal `quantity`, a reason, and a UUID `idempotency_key`. Transfers also require `destination_id`; adjustments require `direction` (`increase` or `decrease`). Quantities should be sent as decimal strings, not floating-point JSON numbers.

## Scope limits and follow-up

Supplier orders and partial receiving are documented separately in [Supplier orders and stock receiving](PURCHASING_ALPHA.md). Job material issue payloads contain `idempotency_key`, `reason`, and `lines`; each line contains `product_id`, `location_id`, and a positive decimal-string `quantity` with three decimal places; use `reservation_line_id` to consume an active job reservation. Reservation requests use `idempotency_key`, `reason`, and similarly shaped `lines`. Inventory remains quantity-only: it does not implement bundles, serial or batch tracking, unit conversions, costing, valuation, tax, invoice integration, or general-ledger posting. No hosted deployment or real business data is part of this increment.
