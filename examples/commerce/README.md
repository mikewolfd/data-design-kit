# Commerce example

These declarations and rows are an independently authored example. They describe orders, customers and a daily revenue calculation; they are not business records.

## What goes in

- `orders` contains six orders, including one cancellation and one unmatched customer.
- `customers` contains three customer-to-region records.
- `read-orders` is a shared reader interface requiring an integer year.
- `amount-cents` is a shared ODCS property definition carrying a quality declaration.

Three designs consume the shared reader. The revenue designs also call the summarization component. The reviewed-revenue design adds an interface-only adjustment component, so its output can be checked as a declaration while plan inference remains unavailable.

## What happens

The authored SQL excludes cancelled orders, matches each remaining order to a customer, and sums integer amounts by date and region. An order without a matching customer is excluded. Duplicate customer keys can multiply totals while preserving a valid output shape. The shared amount definition specifies minor currency units; currency, scale, tax treatment and gross or net basis are unspecified. Region labels do not define geographic boundaries.

The component identifies SQL format, dialect, and semantic requirements. The separate bindings select the proposed DocSpec bounded-job adapter and limits. The first product release tests SQL directly and executes saved Substrait bytes against the same expectations. Managed dataset selection qualifies separately. Binding the orders reader's output supplies test data and does not execute the reader.

The CSV bindings also describe the file-intake example. Current ordinary DocSpec jobs do not directly establish CSV input support. The first fixture runner can encode the explicitly authored fixture rows as temporary JSON Lines with a recorded schema. Running the CSV bindings themselves requires a separately qualified read/conversion path; no such runtime support is claimed here.

## What comes out

| Day | Region | Amount in minor currency units |
| --- | --- | ---: |
| 2026-01-05 | north | 1700 |
| 2026-01-05 | south | 500 |
| 2026-01-06 | north | 250 |

Expected rows in the fixture were specified independently. The documentation checker verifies these totals using the authored SQL in an in-memory SQLite database. That is example sanity checking, not Substrait execution or native-adapter conformance.

## Verification status

The maintained connected workflow test checks actual staging, saved Substrait execution, output quality and a catalog-bound read when the required native tools are explicitly supplied. Its retained receipts establish only the exact files and definitions they name. Changing a description changes definition bytes; an older receipt must not silently become evidence for the revised definition. Catalog metadata checks and native execution remain separate results.

See the [catalog example](catalog/README.md) for ODPS ports, exact version and release records, DCAT discovery, and OpenLineage events.
