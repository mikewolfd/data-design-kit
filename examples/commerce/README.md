# Commerce example

These declarations and rows were independently authored for the DDK engineering draft. They demonstrate the proposed formats; there is no DDK runtime here.

## What goes in

- `orders` contains six orders, including one cancellation and one unmatched customer.
- `customers` contains three customer-to-region records.
- `read-orders` is a shared reader interface requiring an integer year.
- `amount-cents` is a shared ODCS property definition carrying a quality declaration.

Three designs consume the shared reader. The revenue designs also call the summarization component. The reviewed-revenue design adds an interface-only adjustment component, so its output can be checked as a declaration while plan inference remains unavailable.

## What happens

The authored SQL excludes cancelled orders, performs an inner join to customer regions, and sums integer cents by day and region. An unmatched customer is excluded by this explicitly chosen join behavior. Duplicate customer keys are a separate future negative fixture because they can multiply totals while preserving a valid output shape.

## What comes out

| Day | Region | Amount in cents |
| --- | --- | ---: |
| 2026-01-05 | north | 1700 |
| 2026-01-05 | south | 500 |
| 2026-01-06 | north | 250 |

Expected rows in the fixture were specified independently. The documentation checker verifies these totals using the authored SQL in an in-memory SQLite database. That is example sanity checking, not Substrait execution or native-adapter conformance.

## Verification status

Separate delivery tooling checked document shapes, local paths and digests, future-case traceability, and the SQL/fixture consistency described above. That tooling is outside this repository. Native dlt, Frictionless, Data Contract CLI, DataFusion, and Substrait checks remain planned.
