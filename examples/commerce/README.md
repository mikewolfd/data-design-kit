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

The component identifies SQL format, dialect, and semantic requirements. The separate bindings select the proposed DocSpec bounded-job adapter and limits. The first product release tests SQL directly and executes saved Substrait bytes against the same expectations. Managed dataset selection qualifies separately. Binding the orders reader's output supplies test data and does not execute the reader.

The CSV bindings also describe the file-intake example. Current ordinary DocSpec jobs do not directly establish CSV input support. The first fixture runner can encode the explicitly authored fixture rows as temporary JSON Lines with a recorded schema. Running the CSV bindings themselves requires a separately qualified read/conversion path; no such runtime support is claimed here.

## What comes out

| Day | Region | Amount in cents |
| --- | --- | ---: |
| 2026-01-05 | north | 1700 |
| 2026-01-05 | south | 500 |
| 2026-01-06 | north | 250 |

Expected rows in the fixture were specified independently. The documentation checker verifies these totals using the authored SQL in an in-memory SQLite database. That is example sanity checking, not Substrait execution or native-adapter conformance.

## Verification status

Separate delivery tooling checked document shapes, local paths and digests, future-case traceability, and the SQL/fixture consistency described above. That tooling is outside this repository. DocSpec integration, native dlt, Frictionless, Data Contract CLI, DataFusion, and Substrait checks remain planned.

See the [catalog example](catalog/README.md) for ODPS ports, exact version and release records, DCAT discovery, and OpenLineage events.
