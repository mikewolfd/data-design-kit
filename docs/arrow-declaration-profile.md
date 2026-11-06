# Arrow declaration and fixture profiles

`urn:ddk:odcs:arrow-declaration:2` maps explicitly selected ODCS declarations to
Arrow schemas and converts small fixture literals without losing representable
values. It is an opt-in declaration and fixture profile. It does not qualify
DocSpec execution, managed reads, whole-data constraints or publication.

The pinned [ODCS schema](../vendor/odcs/3.2.0/odcs-json-schema.json) owns document
shape and option names. The mapper validates that shape using the offline
registry, preserves the input declaration and inserts no schema defaults. In
particular, the schema's integer `i32` default and the inconsistent `i32` default
annotation under number format do not select physical types. Number formats in
this schema are `f32` and `f64`; `precision` and `scale` are not valid number
options. Native observed `Decimal128` support is a separate capability.

The existing `urn:ddk:odcs:arrow-scalar:1` remains the default for the existing
SQL preparation and fixture paths. It retains its original scalar spellings and
nullable fixture behavior. Nonempty logical options now refuse in that profile,
so an authored `i32` no longer silently becomes `Int64`. Selecting the recursive
profile does not change the meaning of an old result or implicitly enable a
native execution profile.

## Supported declarations

| ODCS declaration | Declared Arrow representation and fixture meaning |
| --- | --- |
| `string` | `Utf8`. Unformatted strings remain strings. `password`, `email`, `uuid`, `uri`, `hostname`, `ipv4` and `ipv6` retain text and require separate format validation. `byte`, `binary` and unrecognized formats refuse; no encoding is guessed. |
| `integer` with explicit format | `i8`, `i16`, `i32`, `i64`, `u8`, `u16`, `u32` and `u64` retain exact signedness and width. Missing format and `i128`/`u128` refuse. Boolean, string and out-of-range fixture values refuse. |
| `number` with explicit format | `f32` or `f64` selects that exact float width. Fixture conversion refuses nonfinite values and any rounding, including inexact decimal literals. Missing format refuses. |
| `boolean` | `Boolean`; only literal booleans or allowed nulls. |
| `date` | `Date32`. Fixture strings use `yyyy-MM-dd`, with a four-digit common-era year and a valid calendar date. An omitted format uses this explicitly selected fixture rule; other date formats refuse. |
| `timestamp` | Explicit `timezone` and a supported format are required. Supported bases are `yyyy-MM-dd HH:mm:ss` and `yyyy-MM-dd'T'HH:mm:ss`, optionally followed by `.SSS`, `.SSSSSS` or `.SSSSSSSSS`. The last form uses nanoseconds; the others use microseconds without rounding. |
| Timestamp with `timezone: true` | Requires a supported format ending in `XXX` and an explicit `defaultTimezone` of `UTC`, `Etc/UTC` or `+00:00`. Fixture offsets must be `Z` or `+00:00`. No nonzero offset conversion or timezone inference occurs. |
| Timestamp with `timezone: false` | Requires a format without an offset and no `defaultTimezone`; retains an unzoned timestamp. |
| `time` | Requires explicit `timezone: false`, no `defaultTimezone`, and `HH:mm:ss` with the same optional fraction widths. Uses `Time64` microseconds or nanoseconds. Zoned times refuse. |
| `object` | Ordered `Struct` children from explicit, nonempty `properties`; child names remain exact. Empty structs and zero-column datasets lack an exact Parquet fixture path here and refuse. |
| `array` | `List` with an explicitly declared `items` type and canonical `element` item name. Parent, item and nested child nullability remain independent. A different explicitly authored item name refuses. |
| `map`, `vector` | Unsupported in this declaration profile. Every supplied option remains explicitly unsupported in coverage. |

Temporal conversion uses integer units, including dates before the Unix epoch.
Invalid calendar/clock fields, leap seconds, incorrect fraction widths, unsupported
offsets and values outside the Arrow integer range refuse. The original request
retains source spelling; the Arrow value represents the declared calendar value
or instant. Converting a timezone or normalizing arbitrary timestamp strings is
outside this profile.

An explicit `physicalName` must equal the modeled name. An explicit `physicalType`
must match the selected canonical primitive Arrow spelling. Opaque SQL type
strings, composite type strings and decimal declarations need a separate mapping
with a named source dialect; this profile does not parse or guess them. It emits
no invented native field IDs. Passing these declaration checks does not admit a
native snapshot or establish the schema actually emitted by an engine.

## Nulls, missing members and validation

Property `required` determines declared Arrow nullability. Object
`logicalTypeOptions.required` lists member names whose presence must be checked;
it does not make those members non-null. String lengths/patterns/formats, numeric
bounds/multiples, temporal bounds, object property bounds/presence, array
length/uniqueness and authored enum/key/quality rules remain explicit
`validation-needed` obligations with status `unknown`. No mapping entry claims
that these data rules ran. Actual checks use the maintained Data Contract CLI or
the supported native evaluator; unsupported required checks must prevent overall
acceptance.

The inventory also retains property `customProperties` entries named `enum`,
root `ddk.rowIdentity` custom properties, and each schema/property relationship,
including relationships on nested fields and list items. Each entry retains the
original object, ordered index in `facet`, structured field/item `path`, and
`scope` (`schema` or `property`). These entries remain `unknown` and
`validation-needed`; they do not imply that a downstream evaluator supports or
has run the check. Legacy enum precedence and JSON-string interpretation stay
with `definitions.enum_values`. Identity declaration checks and relationship
resolution stay with their maintained owners. Repeated declarations, malformed
legacy values and unavailable relationship targets remain visible for those
owners to assess; the mapper neither resolves nor discards them.

New-profile fixtures preserve `null`, `[]`, `[null]` and nested nullability.
Ordinary Arrow struct fields cannot distinguish an absent member from a present
null member. Missing modeled members therefore refuse, even when nullable,
instead of becoming invented nulls. Extra members also refuse. A source that
needs absence semantics must supply its existing explicit presence information
as modeled data before Arrow conversion. This mapper does not create a new
presence format or silently fill values.

## Invocation and evidence

### Observing managed output schemas

`urn:ddk:metadata:arrow-odcs:2` reuses this declaration mapper to compare retained
Arrow schema metadata to a captured ODCS declaration. It is selected explicitly
per output dataset through `assemble_catalog(managed_schema_profiles=...)`.
The original managed definition identity retains that selection. The existing
managed interpreter remains the default and is not broadened implicitly.

The observer preserves ordered field paths and exact observed types and
nullability. A wrong known type, nested shape, field order, unit, zone or list
item name fails. An unsupported declaration or native field-ID convention stays
unknown; there is no fallback to the old interpreter or SQL type inference.
Nullable supply for a required field retains a required-value obligation.
Nonnullable supply satisfies that field's nullability fact. Other authored value
obligations remain unknown until their maintained owner supplies exact evidence.
Metadata interpretation reads no rows and does not itself accept or select a
native candidate. [Observer tests](../tests/test_arrow_observation.py) use
independently constructed Arrow schemas to exercise these distinctions.

### Declaring fixtures

`arrow_schema(dataset, profile=DECLARATION_PROFILE)` returns the declared schema
and per-facet coverage. `map_declaration` captures the declaration once and shares
it between schema construction and fixture conversion. PyArrow is injected only
when constructing physical fixture tables; core mapping imports no engine.

An explicitly invoked `fixture-files` request can select the new profile with
`mappingProfile: "urn:ddk:odcs:arrow-declaration:2"`. The result identifies that
profile, scopes success to `fixture-materialization-only`, records
`dataValidation: "not_run"`, and retains every input's `mappingCoverage` and
`validationObligations`. The ordinary scalar request retains its previous
receipt shape. Frictionless intake and dlt staging retain their existing,
separately bounded flat profiles; this selector does not broaden either one.

The focused [conformance cases](../tests/test_arrow_declarations.py) read real
Parquet outputs with independent expected types and values, exercise each pinned
option category, retain pending enum/identity/relationship declarations through
fixture materialization, refuse lossy and ambiguous values, and pass a deliberately bad
minimum value to the maintained evaluator. That evaluator must detect the
violation even though fixture materialization succeeds. Native canonicalization
can widen small integers or change unsigned types; these Parquet checks do not
establish end-to-end DocSpec type preservation. A native profile requires its own
observed-schema and value evidence.

The declaration profile bounds recursive depth and total fields. These are
metadata bounds, not a whole-process memory claim or support for bulk fixture
generation. Ordinary dataset processing belongs to the maintained runtime.
