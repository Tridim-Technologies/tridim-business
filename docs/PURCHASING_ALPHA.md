# Supplier orders and stock receiving in the synthetic alpha

**Status:** Quantity-only supplier ordering and receiving; no purchasing valuation or accounting

Purchasing extends the inventory catalog with a minimal supplier directory, draft supplier orders, issue/cancel transitions, and partial or full receiving into a stock location. Each accepted receipt creates immutable, linked inventory receipt movements in the same database transaction.

## Supplier records

- A supplier has an organization-unique, case-insensitive code, name, active state, creator, and timestamps.
- Supplier codes and names are copied onto each order when it is created. Later supplier edits do not rewrite order history.
- Only active suppliers may be used for new drafts or issue an existing draft.
- No contact person, email, telephone, address, tax number, or payment details are collected in this increment.

## Supplier orders

Orders contain one or more active products and a positive quantity in each product's base unit. Each product may appear once per order. The order snapshots product SKU, name, and base unit when the draft is created or changed.

| Status | Meaning |
|---|---|
| Draft | Editable or deletable. It has not been issued to the supplier. |
| Issued | Frozen order awaiting receipts. |
| Partially received | At least one quantity was received and more remains. |
| Received | All ordered quantities have been received. |
| Cancelled | An issued or partially received order was cancelled. Past receipts remain recorded and are not reversed. |

Issuing and cancelling are safe to retry. Cancelling a draft is not supported; delete the draft instead. Received lines cannot be edited. Partial receipts can span multiple receipts and locations, but total received quantity cannot exceed the amount ordered.

## Receiving and inventory history

Each receipt request specifies one active location and one or more order-line quantities. A successful request creates a receipt record, receipt lines, and a linked immutable `receipt` stock movement per received line. Order received/remaining quantities and status are derived from receipt history. The order, receipt lines, and movements are committed atomically; if movement creation fails, no part of the receipt is retained.

Receipts require an organization-scoped UUID idempotency key. Retrying the same order, location, and quantities returns the original receipt. Reusing the key for a different receipt returns a conflict. Quantity input uses exact decimal strings with three decimal places; floating-point JSON values are rejected.

## Access

- Owners, administrators, and operations members can manage suppliers, drafts, order transitions, and receipts.
- Owners, administrators, operations, sales, and finance members can read supplier and order history.
- Other roles cannot read the purchasing API.
- Every endpoint and object lookup is scoped to the selected organization.

## API

All routes are organization-scoped beneath `/api/organizations/{organization_id}`.

| Route | Methods | Purpose |
|---|---|---|
| `/purchasing/` | GET | Suppliers, purchase orders with order/receipt history, products, and locations |
| `/purchasing/suppliers/` | POST | Create a supplier |
| `/purchasing/suppliers/{supplier_id}/` | PATCH | Update supplier code, name, or active state |
| `/purchasing/orders/` | POST | Create a draft with supplier and product lines |
| `/purchasing/orders/{order_id}/` | PATCH, DELETE | Replace draft fields/lines or delete a draft |
| `/purchasing/orders/{order_id}/issue/` | POST | Issue and freeze a non-empty draft |
| `/purchasing/orders/{order_id}/cancel/` | POST | Cancel an issued or partially received order |
| `/purchasing/orders/{order_id}/receipts/` | GET, POST | List receipts or record a partial/full receipt |

An order line has `product_id` and `ordered_quantity`. A receipt request has `location_id`, `idempotency_key`, and `lines`, each with `order_line_id` and `quantity`. Quantities are decimal strings, such as `"2.500"`.

The inventory movement response includes `supplier_order_reference` when a receipt movement originates from an order. Standalone inventory receipts remain available and are not attributed to supplier orders.

## Scope limits and follow-up

This is quantity planning and receipt tracking. It does not capture prices, currency, tax, freight, supplier invoices, accounts payable, payments, approval chains, email, external integrations, reservations, costing, valuation, or general-ledger entries. It does not change the inventory unit or valuation model. Use synthetic data only; no hosted deployment or real business data is part of this increment.
