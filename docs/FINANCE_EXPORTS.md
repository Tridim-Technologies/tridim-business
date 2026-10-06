# Finance CSV exports

**Status:** Operational exports for manual invoice and payment records; these are not accounting statements

The finance page offers three organization-scoped CSV downloads: invoices, payments, and payment allocations. Only an owner, admin, or finance member of the selected organization can download them. Each export includes all records for that organization, including voided invoices and reversed payments or allocations.

## File format

- Files use UTF-8 with a byte-order mark and RFC-style CSV quoting with CRLF line endings.
- The first row gives `export_as_of_utc`; the second row defines the balance and state fields; the third row contains column headings. Every data row repeats the `export_as_of_utc` value.
- Dates use `YYYY-MM-DD`. Timestamps use UTC ISO 8601 ending in `Z`.
- Amounts are decimal strings with exactly five fractional digits and an explicit currency column. The exports preserve the product's internal precision; they do not apply currency-specific settlement rounding.
- Untrusted text starting with spreadsheet formula characters is prefixed with an apostrophe. CSV quoting also protects commas, quotation marks, and line breaks.
- The timestamp marks when export generation begins. Rows stream from the database, so concurrent changes can affect a file while it is being produced; the three downloads are not a coordinated transaction snapshot.

## Invoice export

`issued_total` is the stored invoice total. `allocated_total` is the exact sum of active allocations from non-reversed payments. For an issued invoice, `outstanding_total` is `issued_total - allocated_total`; `payment_state` is `unpaid`, `partial`, or `paid`. A void invoice retains its recorded total and history, but has a blank outstanding amount and state `void`.

The export includes invoice/customer/job identifiers, customer-name snapshot, status, issue and due dates, currency, issue actor/time, and void reason/actor/time.

## Payment export

`allocated_total` sums active allocations for an active receipt. `unapplied_total` is the receipt amount less that sum. `payment_state` is `unapplied`, `partially_applied`, `applied`, or `reversed`; reversed receipts have zero allocated and unapplied totals while their original amount and reversal history remain present.

The export includes payment/customer identifiers, customer-name snapshot, received date, amount, currency, method, reference, state, actor/time, and reversal reason/actor/time.

## Allocation export

Every allocation remains in the export. `allocation_state` is `active` or `reversed`; `payment_state` separately describes whether its receipt is active or reversed. Rows include payment/invoice/customer identifiers, invoice number, amount/currency, allocation actor/time, and reversal reason/actor/time.

These files support a finance team's external review of the app's operational records. They do not import bank statements, perform matching, calculate tax, recognize revenue, or provide a balanced ledger or jurisdiction-specific accounting report.
