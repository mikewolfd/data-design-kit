# Data Design Kit 0.1 — Engineering Specification

**Independent Editor's Draft — November 5, 2026**

| Document property | Value |
| --- | --- |
| Short name | DDK |
| Specification version | 0.1 |
| Document status | Independent draft; local implementation qualification is recorded separately |
| Normative artifacts | This document, the versioned schemas, and the normative adapter requirements explicitly linked here |
| Implementation roadmap | [Implementation plan](implementation-plan.md) |
| Public-source evidence | [References](references.md) |
| Original-material license | Apache-2.0 |

## Abstract

Data Design Kit (DDK) connects maintained data product and dataset definitions to native records of what projects captured, ran, checked, and made available. It generates a catalog that helps people and agents discover datasets, choose exact versions, use the correct keys and access methods, and understand what the available evidence supports.

DDK checks reusable reader and transformation interfaces, declared compatibility, and downstream effects before execution. Its first product release combines ODPS product definitions, ODCS dataset definitions, JSON Schema parameters, DCAT 3 discovery, OpenLineage design and run events, and a tested Substrait execution path. Executed fixtures and data checks link results to exact inputs, outputs, and rules.

## Status of this document

This is a new engineering proposal. It follows the organization and conformance discipline of W3C technical reports but is not a W3C publication. It carries no W3C, Bitol, or Apache endorsement. No runtime behavior is implemented by publishing this draft.

The [local release record](local-release.md) identifies an independently implemented prerelease and the exact profile claims supported by its executed evidence. This document remains a draft.

Examples and conformance expectations were written independently for this project. Public upstream artifacts retain their own provenance. See [PROVENANCE.md](../PROVENANCE.md).

This draft defines the catalog and checker profiles, document shapes, and release evidence needed for implementation. The Substrait producer and consumer combination must be qualified by executing a saved plan. A standalone validator and any additional engine have separate qualification requirements.

## Table of contents

1. [Purpose and boundaries](#purpose)
2. [Conformance](#conformance)
3. [Terms and data model](#model)
4. [Document syntax](#syntax)
5. [Projects and reference resolution](#resolution)
6. [Component interfaces and arguments](#interfaces)
7. [Dataset compatibility](#datasets)
8. [Design graphs and outputs](#graphs)
9. [Project policies and shared definitions](#policies)
10. [Core checking algorithm](#checking)
11. [Change impact](#impact)
12. [Locks and reproducibility](#locks)
13. [Results and diagnostics](#results)
14. [Command-line behavior](#cli)
15. [Integration profiles](#integrations)
16. [Security, privacy, and resource limits](#security)
17. [Versioning and extensibility](#versioning)
18. [Conformance evidence](#evidence)
19. [Data product catalogs](#catalog)
20. [References](#references)

<a id="purpose"></a>
## 1. Purpose and boundaries

### 1.1 Intended users and outcomes (informative)

Consumers use the catalog to find data by purpose, understand row meaning and coverage, choose a supported version and access method, and use documented relationships and query examples. A maintainer can trace a result to its inputs and identify known consumers and required checks affected by a proposed change.

The same maintained definitions supply the checker, catalogs, dictionaries, and consumer metadata. Projects can adopt an existing authoritative definition through an adapter before changing where they author it. Catalog files and compatibility outputs are generated from that owner. Native records supply capture, execution, version, and publication facts. Projects can describe retained originals, faithful source records, derived datasets, and application datasets using their own storage and publication arrangements.

### 1.2 Ownership of existing standards (informative)

ODPS describes the product and its ports. ODCS describes dataset meaning, schema, and requirements. JSON Schema validates structured parameters. DCAT 3 describes discovery, versions, and access. OpenLineage exchanges declared job dependencies and actual run observations. Substrait represents supported executable plans. DDK connects these artifacts and adds bounded reference, compatibility, impact, and evidence checks.

The initial execution path uses DocSpec for SQL and saved Substrait plans through its DataFusion context. The integration plan retains Data Contract CLI for ODCS checks, Frictionless for structured files, dlt for ingestion, and pytest for independently authored fixtures. Each adapter qualifies its supported operations and version combination separately.

Project code owns acquisition, parsing, domain rules, and transformations. The execution system owns computation, recovery, and native protection. Publication owners supply release membership and selection. DDK links their records and evaluates the requirements for a stated purpose. DocSpec is team-owned and unreleased. The plan identifies the API and runtime capabilities it needs to add.

### 1.3 Deployment boundary (informative)

The initial catalog is a set of generated files and existing consumer formats. Projects retain their native storage and publishers. Cross-project checks cover explicitly loaded definitions and records. The offline checker uses document metadata, and execution adapters operate through explicit requests.

<a id="conformance"></a>
## 2. Conformance

### 2.1 Normative language

The uppercase terms defined by BCP 14, including **MUST**, **MUST NOT**, **SHOULD**, and **MAY**, have their RFC 2119 and RFC 8174 meanings. Lowercase uses carry their ordinary meaning. Sections marked informative, examples, rationale, architecture decisions, and the implementation plan are non-normative. Numbered requirements with `DDK-` identifiers and the versioned format schemas are normative.

<a id="DDK-CONF-001"></a>
### DDK-CONF-001 — Product classes and claims

A conforming product MUST identify its specification version and claimed product classes: **document producer**, **core checker**, **impact analyzer**, **catalog producer**, **adapter**, or **report consumer**. An implementation MUST claim each optional profile separately and MUST identify the tested dependency versions. Support for one profile MUST NOT imply support for another.

<a id="DDK-CONF-002"></a>
### DDK-CONF-002 — Required profiles

`core` is mandatory for a core checker. Command-selected profiles are `impact`, `catalog`, `catalog.dcat`, `lineage.openlineage`, `odcs-cli`, `files.frictionless`, `ingest.dlt`, `plan.docspec-sql`, `execute.docspec-job`, `runtime.docspec-managed`, `plan.datafusion`, `plan.substrait-validator`, `test.fixtures`, and `test.portability`. The `catalog` profile includes ODPS resolution and the checks in Section 19. `plan.datafusion` covers saved Substrait production and consumption through DocSpec. The first product release has a separate profile requirement in DDK-VERSION-003.

`core` operates on local declarations and a local schema registry. A checker MUST complete it without selecting an execution engine, importing component implementation modules, contacting databases, reading production rows, or using network access. `catalog` MUST support local generation from explicit metadata inputs without opening the data payloads they describe.

<a id="DDK-CONF-003"></a>
### DDK-CONF-003 — Partial support

A checker MUST enumerate the checks requested by the project and command. An unsupported, indeterminate, or unavailable required check MUST produce `unknown` or `not_run` and MUST prevent an overall `passed` decision. Partial ODCS interpretation MUST be reported as a DDK compatibility limit rather than as invalid ODCS.

<a id="DDK-CONF-004"></a>
### DDK-CONF-004 — Normative artifacts and conflicts

The schemas in `schemas/0.1/` define DDK document shapes. This specification defines semantics and algorithms. The pinned ODCS, ODPS, and OpenLineage schemas define the upstream document and event shapes used by their profiles. An unresolved contradiction between these artifacts MUST block a conformance claim for the affected requirement. Implementers MUST report the contradiction rather than selecting a permissive interpretation silently.

<a id="model"></a>
## 3. Terms and data model

| Term | Meaning |
| --- | --- |
| Project | An explicitly enumerated set of artifacts, imported projects, and requested checks. |
| Artifact | A registered dataset, ODPS product, component, design, property definition, or policy document. |
| Dataset definition | One selected schema object from an ODCS document. |
| Dataset identity | A stable catalog identifier shared by revisions of the same logical dataset. |
| Data product | An ODPS definition with named ports linked to dataset definitions. |
| Dataset version | An exact native reference to data associated with a specific dataset definition. |
| Representation | A file set, table, or service through which a dataset version can be read. |
| Release | A publisher-owned composition of exact dataset versions. |
| Selection | An authority's choice of a release for a named consumer purpose. |
| Component | A versioned reader or transformation interface, optionally linked to implementation material. |
| Design | Calls to components, source datasets, parameter declarations, and named exports. |
| Port | A named component input or output associated with a dataset definition. |
| Declared evidence | A checked relationship among authored declarations; actual data and implementations remain assumptions. |
| Inferred evidence | A property derived by a compiler, planner, or supported static algorithm. |
| Executed evidence | A property observed by running a test or examining actual data. |
| Binding | An explicit association between a logical input and a fixture, file set, or immutable runtime-native version. |
| Bounded job | Explicit execution that reports observed outputs and partial failure, without implying durable recovery. |
| Managed operation | Runtime-owned work with a stable operation identity, retained phases, reconciliation, and guarded selection for a supported operation/backend pair. |
| Candidate | An exact retained result prepared by a runtime but not necessarily selected for consumers. |
| Qualification | Evidence that identified rules were evaluated against an exact candidate; runtime acceptance is separate from report validity. |
| Effective definition | The result of applying the documented ODCS definition-resolution rules. |
| Check instance | One named question about a particular artifact, call, rule, or output. |
| Lock | An inventory of exact input bytes, tool versions, and transitive references used for a run. |

<a id="DDK-MODEL-001"></a>
### DDK-MODEL-001 — Identity and aliases

Every DDK document MUST have `specVersion`, `kind`, `id`, and `version`. `id` MUST be an absolute URI used as an identifier, without implicit dereferencing. `version` MUST be a Semantic Versioning 2.0 version. Artifact aliases are project-local names; identity comparisons MUST use the document identity and version rather than an alias. For a dataset definition, identity also includes the selected ODCS schema object's stable ID, or its exact name when no stable ID exists. Catalog identity and native data version follow DDK-CATALOG-003.

Artifact, namespace, source, and step aliases use the restricted alias grammar. Named component ports and JSON Schema parameter properties may use any nonempty string and remain case-sensitive; they are not restricted to filesystem-style aliases.

<a id="DDK-MODEL-002"></a>
### DDK-MODEL-002 — Evidence does not escalate implicitly

A checker MUST preserve the evidence level attached to a claim. A component's promised output MUST remain declared evidence until an independent plan inference or execution supplies stronger evidence. A valid interface declaration MUST NOT be reported as proof that an implementation accepts its arguments or produces its promised rows.

<a id="DDK-ARCH-001"></a>
### DDK-ARCH-001 — Domain and injection boundary

The domain MUST own interfaces, declared datasets, dependency relationships, compatibility rules, policies, and check results without depending on external implementation types or packages. Standard concepts MAY remain in its model. Application use cases MUST receive external services through explicit dependency injection. The composition root MUST select concrete adapters; installation MUST NOT enable an adapter or change existing behavior. Document loading, CLI transport, native tools, and execution services MUST remain outside the domain. Interfaces MUST serve a concrete use case; this requirement does not require a generic plugin framework or empty layers.

<a id="syntax"></a>
## 4. Document syntax

<a id="DDK-SYNTAX-001"></a>
### DDK-SYNTAX-001 — JSON and YAML

A producer MUST support JSON documents conforming to RFC 8259. A checker MUST support JSON and MAY also support YAML 1.2. Supported YAML MUST map to the JSON data model. Duplicate mapping keys, merge keys, aliases, custom tags, non-string object keys, non-finite numbers, and implicit date objects MUST be rejected. YAML support MUST preserve JSON boolean and number meanings. UTF-8 decoding errors are document failures.

<a id="DDK-SYNTAX-002"></a>
### DDK-SYNTAX-002 — Schema validation and locations

A checker MUST validate DDK documents against the matching Draft 2020-12 schemas and ODCS documents against their declared supported dialect. This draft's ODCS profile accepts `apiVersion: v3.2.0` and validates against the pinned ODCS 3.2.0 schema at GitHub revision `448f7b93329ece7827897d7dd51e827a3e279460`, whose own dialect is Draft 2019-09. The revision is part of the profile and lock, not inferred from `apiVersion`. It MUST retain source locations at least as a path and RFC 6901 JSON Pointer. Line and column locations, when emitted, MUST be one-based.

<a id="DDK-SYNTAX-003"></a>
### DDK-SYNTAX-003 — Keywords and literals

Unknown DDK structural properties MUST be rejected except within the explicit `extensions` object. User-authored JSON Schema values, JSON literals, ODCS custom properties, and adapter-owned configurations retain the extension rules of their respective standards. A checker MUST distinguish an unrecognized required extension from an optional annotation. JSON Schema `default` is an annotation and MUST NOT insert argument values.

<a id="DDK-SYNTAX-004"></a>
### DDK-SYNTAX-004 — Value comparison

Object-member ordering is insignificant; array ordering is significant unless a rule explicitly states otherwise. Field and alias names are case-sensitive. A checker MUST distinguish booleans from numbers and MUST compare numeric bounds without introducing binary floating-point rounding errors. It MUST preserve original bytes separately for hashing. String identifiers MUST NOT be case-folded or Unicode-normalized implicitly.

<a id="resolution"></a>
## 5. Projects and reference resolution

### 5.1 Project document

The project schema is [project.schema.json](../schemas/0.1/project.schema.json). `artifacts` maps aliases to `{kind, path}` entries. Dataset entries also specify `object` and may specify `catalogId`, `role`, and `attribution` (DDK-CATALOG-003). A `product` entry names an ODPS document. `imports` maps namespace aliases to other projects. An aggregator project has no artifacts of its own and imports at least one project; a project with neither is invalid. `requiredChecks` lists check groups that gate the result. An optional `catalog` section supplies the catalog identifier and any port bindings, relationship extensions, and query examples. The [commerce project](../examples/commerce/project.ddk.json) illustrates both design checking and catalog inputs.

<a id="DDK-REF-001"></a>
### DDK-REF-001 — Paths and namespaces

A document-relative path MUST resolve from the directory containing that document. Each artifact reference MUST resolve in its declaring project's namespace. A reference beginning with `/` is root-relative; other references are relative to the declaring namespace. `/` separates namespace segments, and each segment follows the alias grammar in the common schema. Parent traversal in artifact aliases is forbidden. Ordinary file paths may use `..` only when their resolved real paths remain inside the explicitly permitted project roots.

<a id="DDK-REF-002"></a>
### DDK-REF-002 — Import traversal

A checker MUST visit the root project and its imports breadth-first over sorted import aliases and load each project file once, at its first occurrence. That occurrence is the shortest import path from the root; ties go to the namespace whose segments sort first. To choose the namespace explicitly, import the project from the root under that alias. Every later path to the same file MUST become an alias of that canonical namespace: references written through it resolve to the canonical artifacts, and the project's artifacts, relationships, and catalog records load once. The report MUST record the import aliases. A checker MUST reject an import cycle, including one reached only through aliases, a duplicate fully qualified alias, conflicting bytes for the same identity and version, and the same project identity and version loaded from another file, whose relative paths could resolve differently. Reuse of the same source document through different aliases is permitted when its bytes and selected dataset object agree. Symlink targets MUST be checked against the same root boundary as ordinary paths.

<a id="DDK-REF-003"></a>
### DDK-REF-003 — Dataset selection

A dataset entry's `object` MUST match an ODCS schema object's stable `id` first, then its exact `name` only when no ID match exists. Zero or multiple matches MUST fail resolution. A checker MUST validate the entire ODCS document, while recording which object was selected. Duplicate object or property IDs and duplicate property names within an interpreted object MUST be reported even when upstream schema validation permits them.

<a id="DDK-REF-004"></a>
### DDK-REF-004 — Shared property definitions

A checker MUST preserve the resolution and override precedence documented by the selected ODCS definition resolver. For the initial `odcs-cli` integration, inline property values win over inherited values. Every followed local definition and fragment MUST enter the lock and reference graph. An unresolved or cyclic required definition MUST fail its reference check. A link of a resolvable type that the selected resolver would fetch — a URL with a host or a non-file scheme, or a fragment-less path without a definition-file suffix — is a documentation reference: the checker MUST NOT follow it or report it as unresolved. A document opts its remote links into resolution with the root `customProperties` entry `{vendor: ddk, property: inlineReferences, value: true}`, as Data Contract CLI's `--inline-references` option does. Such a definition requires unavailable remote resolution and MUST remain `unknown`; the checker MUST NOT substitute an empty definition.

<a id="DDK-REF-005"></a>
### DDK-REF-005 — Complete and bounded scope

The report MUST enumerate loaded project namespaces, selected artifacts, followed references, and requested selection filters. An impact analyzer MUST restrict claims to that inventory. A checker MUST NOT infer that all consumers in an organization were checked merely because a repository or package was scanned.

### 5.2 Resolution example (informative)

A root project imports `shared/project.ddk.json` as `shared`. A design in the root refers to `shared/read-orders`. A component defined inside that imported project refers to its local `orders` dataset. That reference resolves to `shared/orders`; it does not bind to the root project's `orders` alias. `/orders` would explicitly select the latter.

<a id="interfaces"></a>
## 6. Component interfaces and arguments

### 6.1 Component document

The component schema is [component.schema.json](../schemas/0.1/component.schema.json). `role` is `reader` or `transform`. `parameters` contains a JSON Schema object. `inputs` and `outputs` map named ports to dataset references. Inputs may be optional and may accept additional fields. Outputs describe promised datasets. `implementation` is optional and is interpreted only by explicitly invoked adapter profiles.

<a id="DDK-CALL-001"></a>
### DDK-CALL-001 — Interface-only components

A core checker MUST accept a valid component without an implementation. It MUST resolve its dataset references and validate its parameter schema without importing or executing implementation code. Every component MUST declare at least one output. Reader and transformation roles MUST use the same call-checking rules.

<a id="DDK-CALL-002"></a>
### DDK-CALL-002 — Named inputs

A call MUST provide every non-optional named input, MUST NOT provide undeclared input names, and MUST reference an existing design source or step output. For each supplied input, the checker MUST compare the available declared dataset with the port's required dataset using Section 7. Optionality concerns whether a port is supplied, not whether its field values may be null.

<a id="DDK-CALL-003"></a>
### DDK-CALL-003 — Tagged arguments

Each argument value MUST be exactly one of `{ "literal": <JSON value> }` or `{ "parameter": "<design parameter name>" }`. Literal objects MUST remain ordinary data and MUST NOT be searched for executable expressions or parameter markers. Missing and unexpected arguments MUST follow the component's JSON Schema `required` and `additionalProperties` rules. An absent argument is distinct from an explicit `null`.

<a id="DDK-CALL-004"></a>
### DDK-CALL-004 — Literal validation

A checker MUST validate each complete literal argument object against the declared parameter schema using the supported JSON Schema dialect. It MUST validate schema syntax before validating instances. Component parameter schemas MUST explicitly declare `type: object`, `properties`, and `additionalProperties: false`; required names MUST exist in `properties`. Schema defaults MUST NOT satisfy missing required arguments.

<a id="DDK-CALL-005"></a>
### DDK-CALL-005 — Symbolic parameter compatibility

A design-parameter reference MUST resolve to a declared parameter. For schemas restricted to primitive `type`, `enum`, `const`, inclusive/exclusive numeric bounds, and nonnegative string or array length bounds, a checker MUST determine whether the source's admitted values are a subset of the target's admitted values. Boolean values are never numeric. Source `integer` may satisfy target `number`, subject to bounds. Unsupported keywords that affect this proof, cross-property conditions, or unresolved references MUST yield `unknown` unless a documented sound extension proves the relation. A disproved relationship MUST fail; a supported relationship MUST pass.

<a id="DDK-CALL-006"></a>
### DDK-CALL-006 — Correlated arguments

When all arguments are literal, the complete parameter object MUST be checked, including supported cross-property constraints. When symbolic arguments occur and whole-object constraints could affect validity, the checker MUST return `unknown` for that whole-object check unless it proves validity or invalidity. Per-argument success MUST NOT erase the whole-object result.

<a id="DDK-CALL-007"></a>
### DDK-CALL-007 — Implementation meaning and runtime placement

An optional `implementation` MUST identify its artifact using `path` or `entrypoint`, its `format`, and a versioned `semantics` profile. SQL MUST also identify its `dialect`. A semantic profile MUST define the applicable function behavior, type mappings, overflow, null, collation, and temporal rules, or mark unsupported facets explicitly. Connection settings, runtime adapter selection, execution mode, and operational limits MUST be supplied separately in bindings or caller configuration. Credentials MUST use the explicit runtime mechanism in DDK-SAFE-002. A runtime endpoint change alone MUST NOT redefine a component; unproven or changed execution semantics MUST prevent reuse under the previous computation identity. Core checks MUST validate the declaration without loading the profile's implementation.

<a id="datasets"></a>
## 7. Dataset compatibility

### 7.1 Initial tabular profile

DDK 0.1 interprets flat ODCS objects with named scalar properties. ODCS remains capable of richer structures. Nested objects, arrays, maps, vectors, omitted logical types, and unsupported type options can be valid ODCS while requiring an `unknown` DDK compatibility result.

<a id="DDK-DATA-001"></a>
### DDK-DATA-001 — Direction of comparison

Compatibility asks whether values and fields promised by an available dataset satisfy the requirements of a consumer. Every property listed by the consumer is a required column in this tabular profile. ODCS property `required` concerns null values and MUST NOT be interpreted as permission to omit the column. Component inputs allow additional available fields by default; design exports forbid them by default. Explicit settings MUST override these defaults and be included in evidence.

<a id="DDK-DATA-002"></a>
### DDK-DATA-002 — Supported field relations

A checker MUST compare exact field names, logical scalar types, nullability, and declared enums. Available logical types MUST match required types, except `integer` may satisfy logical `number` when other supported restrictions permit it. Available nullable values cannot satisfy a required non-null field. Available enum values MUST be a subset of required enum values when the consumer restricts them. A missing available enum supplies no such restriction. ODCS enum entries MUST be compared using their `value`, not their label. These checks establish relationships among declarations only.

<a id="DDK-DATA-003"></a>
### DDK-DATA-003 — Unknown restrictions and physical types

Any consumer restriction that the checker cannot interpret MUST yield `unknown` unless independently disproved. Physical types, decimal precision and scale, integer widths, timestamps, time zones, and engine-specific coercions MUST be handled only by a versioned mapping profile with stated rules. The checker MUST NOT assume that logical `number` means a particular floating-point or decimal representation. Missing information MUST NOT be replaced with an engine default silently.

<a id="DDK-DATA-004"></a>
### DDK-DATA-004 — Defaults and claims

For this comparison only, omitted ODCS `required` means nullable, following the pinned standard's default. Omitted `unique` supplies no uniqueness guarantee. Declared uniqueness, keys, and row identity MUST be recorded as assumptions until actual-data checks establish them for a particular snapshot. Column compatibility MUST NOT be reported as proof of join cardinality, correct aggregation, uniqueness, or business meaning.

<a id="DDK-DATA-005"></a>
### DDK-DATA-005 — Aggregating field decisions

A dataset comparison MUST fail when any field relation is disproved or forbidden extra fields exist. Otherwise it MUST be `unknown` when any applicable relation is indeterminate, and `passed` when all applicable relations are established. Field ordering is irrelevant to declared compatibility but MUST be preserved when mapping to positional execution formats. A checker MUST report the complete mapping rather than relying on coincidental column order.

<a id="DDK-DATA-006"></a>
### DDK-DATA-006 — Stored and view properties

A property annotated with the `customProperties` entry `{vendor: ddk, property: storage, value: view}` is computed from stored properties of the same selected object. It MUST name them in ODCS `transformSourceObjects` and give its expression in `transformLogic`. Every named source MUST be a top-level property of the same object that is not itself a view; a property annotated `stored`, or without a DDK storage annotation, is stored. A property MUST carry at most one DDK storage annotation, valued `stored` or `view`. The checker evaluates these annotations for each selected dataset that carries them. Storage annotations of other vendors remain their owners' and are not interpreted. Success establishes declaration consistency only, not that the logic computes the property.

<a id="graphs"></a>
## 8. Design graphs and outputs

The design schema is [design.schema.json](../schemas/0.1/design.schema.json). A design declares its parameters, external `sources`, component `steps`, and named `exports`. A source is a dataset declaration, not evidence that actual rows exist. A step refers to a component and supplies named inputs and tagged arguments.

<a id="DDK-GRAPH-001"></a>
### DDK-GRAPH-001 — Reference and cycle checks

Every step component, source, output port, and export origin MUST resolve. The checker MUST construct an edge from each producing step to each consuming step and MUST reject a cycle, including a self-cycle. Step maps provide unique names by construction; duplicate keys MUST already have failed parsing. Topological scheduling MUST choose lexicographically smallest ready names to produce deterministic order.

<a id="DDK-GRAPH-002"></a>
### DDK-GRAPH-002 — Multiple outputs

A design MUST declare at least one named export. Each export MUST specify an origin and an expected dataset. A checker MUST compare every export separately. Multiple sinks, multiple component outputs, and direct exports of sources are permitted. An unconnected step SHOULD produce a warning; it MUST NOT cause the checker to guess which output a user intended.

<a id="DDK-GRAPH-003"></a>
### DDK-GRAPH-003 — Declared and inferred outputs

Core export checks MUST use the origin component's declared output or the source's declared dataset. Inferred output checks MUST run as separate instances under a plan profile. Missing implementations or unsupported inference MUST remain visible as `not_run` or `unknown` for those plan checks. The core checker MUST NOT recognize operation names and invent output columns using private transformation rules.

<a id="DDK-GRAPH-004"></a>
### DDK-GRAPH-004 — Determinate failures and dependent checks

A failed reference or cycle check MUST block checks that require that relationship. Blocked dependent checks MUST be `not_run` with an explicit dependency reason. Independent artifacts and check instances SHOULD continue so that one run can report several actionable problems. A checker MUST preserve the original failure even when later checks are blocked.

<a id="policies"></a>
## 9. Project policies and shared definitions

The policy schema is [policy.schema.json](../schemas/0.1/policy.schema.json). A policy document contains stable rule IDs and typed rule configurations. Core rules are `fields-exist`, `row-identity`, `quality-fields`, `vocabulary`, and `layer-order`. Adapter coverage is requested through explicit check groups and adapter capabilities rather than a handwritten mapping-completeness list.

An extension rule uses an absolute URI as its `check` value and places its arguments in `configuration`. A core checker can therefore parse an unrecognized rule and report unknown coverage without accepting arbitrary structural keys.

<a id="DDK-POLICY-001"></a>
### DDK-POLICY-001 — Explicit rules

A checker MUST validate each policy's rule shape, resolve its targets, and emit a separate result for each rule. Rule IDs MUST be unique within a policy. An unsupported required rule MUST be `unknown`. Optional extensions MUST be preserved as metadata but MUST NOT be credited as evaluated controls.

<a id="DDK-POLICY-002"></a>
### DDK-POLICY-002 — Fields and row identity

`fields-exist` MUST check exact names in the selected dataset. `row-identity` MUST read the selected ODCS object's `customProperties` entry with `vendor: ddk` and `property: rowIdentity`; its value MUST be a nonempty array of unique field names. Missing or malformed annotations and absent fields MUST fail. Duplicate entries for the same DDK property MUST fail. Success establishes declaration consistency only, not uniqueness of rows.

<a id="DDK-POLICY-003"></a>
### DDK-POLICY-003 — Quality field dependencies

`quality-fields` MUST visit object-level and property-level ODCS quality rules in the selected object. Property-level rules implicitly depend on their containing property. Additional declared dependencies use `customProperties` with `vendor: ddk`, `property: fieldDependencies`, and a unique array of field names. The checker MUST reject missing referenced fields. For SQL or custom rules with no complete dependency declaration, the dependency-completeness instance MUST be `unknown`; parsing SQL is not a core requirement. Presence of SQL text MUST NOT imply SQL correctness or execution.

<a id="DDK-POLICY-004"></a>
### DDK-POLICY-004 — Vocabulary rules

`vocabulary` MUST resolve its target artifact and RFC 6901 pointer, then compare its selected JSON value with `allowed`. When `each` is true, the selected value MUST be an array and every element MUST be allowed. A missing pointer, wrong selected shape, or disallowed value MUST fail. A checker MUST distinguish this explicit project policy from the upstream standard's own allowed values.

<a id="DDK-POLICY-005"></a>
### DDK-POLICY-005 — Shared-definition use and overrides

A checker MUST inventory references to registered shared property definitions and SHOULD warn about definitions with no loaded consumers. Definitions containing quality arrays MUST be included in this inventory. Resolution MUST record which values are inherited and which are overridden. Core MUST report that override precedence was applied, without asserting that an override preserves every inherited restriction. An impact check requesting non-weakening MUST use the supported subset relation and return `unknown` for unsupported relationships.

<a id="DDK-POLICY-006"></a>
### DDK-POLICY-006 — Layer order

A `layer-order` rule lists layers from lowest to highest; each names loaded project namespaces, resolved like artifact references and through import aliases. An artifact belongs to the layer of its longest matching namespace. The rule checks declared dependencies: each resolved product port against its product, each relationship target against its source dataset, each recipe input against the recipe's declaring namespace, and each component input or design source against its production. A dependency that points to a higher layer MUST fail. A dependency with an endpoint outside every layer, or one that does not resolve, MUST make the rule `unknown`. Repeated layer names, namespaces assigned to two layers, and namespaces that are not loaded MUST fail. External relationship endpoints are outside the rule. Success establishes declared direction only, not observed data flow.

### 9.1 Extension ownership (informative)

The `ddk` custom-property vendor identifier in this draft is a proposal for this project's annotations: `rowIdentity`, `fieldDependencies`, `storage`, and `inlineReferences`. It is not an ODCS standard feature. Existing ODCS extensions keep their original ownership. A future CUE adapter can add policy evaluation without requiring all authors to write CUE or altering the core declarations.

<a id="checking"></a>
## 10. Core checking algorithm

<a id="DDK-CHECK-001"></a>
### DDK-CHECK-001 — Processing order

A core checker MUST perform these stages in order, while continuing independent work after known failures:

1. Parse the command and identify requested profiles and permitted roots.
2. Parse project documents, check their schemas, and traverse imports.
3. Parse registered artifacts, validate document shapes, and index identities.
4. Resolve local ODCS references and record effective values and provenance.
5. Build artifact and step dependency graphs; detect unresolved references and cycles.
6. Validate component parameter schemas, literal calls, symbolic calls, and named ports.
7. Compare declared input datasets and every design export; check stored and view properties.
8. Evaluate explicit project policies and shared-definition usage.
9. Add requested optional-profile instances, including unavailable capabilities.
10. Compute the overall decision from check outcomes and write the report.

A stage MUST NOT consume an invalid prerequisite as if it were a valid empty object. Catalog reference resolution and evidence assessment run only for the requested catalog profiles. A relationship used to navigate data MUST NOT enter the execution-step cycle check unless the design also declares a production dependency.

<a id="DDK-CHECK-002"></a>
### DDK-CHECK-002 — Check inventory and selection

The mandatory core groups are `core.documents`, `core.references`, `core.graph`, `core.calls`, `core.datasets`, and `core.policies`. A root project's `requiredChecks` MUST include these groups. Optional groups are listed in Section 15. A selection filter MUST include transitive prerequisites, MUST report excluded consumers, and MUST NOT be used to claim full-project coverage. An artifact with no applicable policy rules has a completed zero-rule inventory, not fabricated policy successes.

<a id="DDK-CHECK-003"></a>
### DDK-CHECK-003 — Bounded repeated work

Within a run, a checker MUST parse each distinct real-path and byte-digest combination once and SHOULD reuse validated effective definitions and compatibility results. Cache keys MUST include relevant schemas, resolver rules, profiles, and adapter versions. A changed dependency MUST invalidate dependent results. Reference and graph analysis MUST operate on indexed relationships rather than repeatedly scanning all documents for each consumer.

### 10.1 Expected algorithmic cost (informative)

Index construction and graph traversal can be linear in the input size and relationship count. Sorting names and a deterministic ready-node heap add ordering costs. JSON Schema validation and symbolic containment have their own costs; the system makes no blanket linear-time promise for arbitrary schemas. The implementation plan defines measured performance gates instead of asserting unmeasured speed.

<a id="impact"></a>
## 11. Change impact

<a id="DDK-IMPACT-001"></a>
### DDK-IMPACT-001 — Explicit snapshots

An impact analyzer MUST accept an explicit base project and candidate project, each with a resolved inventory. It MUST compare document identities and versions, record content changes, and preserve each snapshot's resolution scope. Changed bytes under the same identity and version MUST produce a version-reuse diagnostic, even when the semantic comparison can continue. Formatting-only changes MAY be classified separately from meaning changes.

<a id="DDK-IMPACT-002"></a>
### DDK-IMPACT-002 — Consumer revalidation

The analyzer MUST find direct and transitive consumers of changed components, dataset definitions, policies, and shared property definitions. It MUST revalidate candidate calls against candidate interfaces and attach dependency paths explaining each impact. Removal of an argument or input name, newly required arguments, changed output ports, and unsupported parameter restrictions MUST be distinguished. A consumer appearing in the impact set does not by itself mean it is broken.

<a id="DDK-IMPACT-003"></a>
### DDK-IMPACT-003 — Compatibility direction

For component parameters and inputs, a backward-compatible candidate accepts at least the values and datasets accepted by the base. For promised outputs, candidate values MUST satisfy base consumer requirements. The analyzer MUST name the comparison direction and MUST apply its supported subset relation accordingly. Dataset-version classification delegated to Data Contract CLI MUST preserve the selected producer or consumer perspective and its original evidence. Unsupported general schema containment MUST remain `unknown`.

<a id="DDK-IMPACT-004"></a>
### DDK-IMPACT-004 — Overrides and scope limits

When non-weakening is requested for a shared definition or override, the analyzer MUST compare effective supported restrictions and identify changed provenance. It MUST report unknown portions rather than assuming that a syntactically valid override is safe. Missing external projects MUST be listed as uncovered scope; automatic organization-wide consumer discovery is outside this profile.

<a id="locks"></a>
## 12. Locks and reproducibility

The lock schema is [lock.schema.json](../schemas/0.1/lock.schema.json). Locks describe exact inputs; they are not a package registry or a secret store.

<a id="DDK-LOCK-001"></a>
### DDK-LOCK-001 — Byte inventory

A lock MUST record SHA-256 hashes of the original bytes for the project closure, followed shared definitions, parameter schemas, implementation sources used by requested profiles, and adapter capability manifests. It MUST record schema versions and revisions, resolver identity and version, selected ODCS objects, and tool versions. Development builds MUST also record the source commit and built-distribution digest, even when their version string matches a release. A catalog lock MUST record the metadata input and disclosure policy bytes, any followed recipe, the requested outputs and audience, the current selection selector when supplied, and the selected metadata adapter when used. Hashing MUST NOT depend on a reserialized YAML or JSON representation. Different objects selected from the same file MUST retain their individual selections and share the byte digest.

<a id="DDK-LOCK-002"></a>
### DDK-LOCK-002 — Locked operation

In `--locked` mode, missing lock entries, changed digests, changed resolution rules, and unexpected followed dependencies MUST fail lock verification before cached results are trusted. The checker MUST NOT update the lock automatically. Unlocked operation is permitted, but the report MUST mark lock verification as absent. A lock command MUST write an explicitly named lock file and MUST preserve a previous file when inventory construction fails.

<a id="DDK-LOCK-003"></a>
### DDK-LOCK-003 — Runtime inputs

Execution evidence MUST additionally identify the executed implementation's bytes and format, any generated job or saved plan, effective bindings, source snapshot identifiers or file digests, parameter values or suitably redacted value fingerprints, semantic profile, and engine versions. Glob patterns MUST be expanded to an explicit file list before execution; the expanded list MUST enter the execution receipt. Native inputs MUST retain their reference scheme, namespace, exact version, and native digest algorithm rather than enter the file inventory as invented exports. Reuse of execution evidence MUST require matching inputs and check semantics. DDK MUST NOT store secrets in locks or reports.

<a id="DDK-LOCK-004"></a>
### DDK-LOCK-004 — Stable and volatile report data

Given the same locked inputs, requested checks, and tool versions, a checker MUST produce the same check identities, outcomes, reasons, and sorted diagnostics. Timestamps, run identifiers, elapsed times, and resource measurements MUST be segregated as volatile metadata. A cache MUST distinguish stable result content from those volatile observations.

<a id="DDK-LOCK-005"></a>
### DDK-LOCK-005 — Computation, qualification, and provenance

The runtime MUST own computation-reuse decisions. DDK MUST preserve runtime-issued computation and qualification identities separately from complete run provenance. Computation identity MUST account for exact consumed versions, schema interpretation and field identities, calculation semantics, and effective parameters. Qualification identity MUST additionally account for the exact candidate, complete required rules, evaluator identity, and evaluation/mapping semantics. A qualification-only change MUST NOT by itself invalidate reusable computed values. Endpoint changes MAY preserve computation identity only when input identity and semantic equivalence remain established. Unknown semantic equivalence MUST prevent reuse. Full tool versions, endpoints subject to redaction, limits, and observations MUST remain available as provenance; neither the whole project lock nor provenance alone is a computation key. DDK MAY cache its own check results under matching check prerequisites without duplicating native phase state.

<a id="results"></a>
## 13. Results and diagnostics

The report schema is [report.schema.json](../schemas/0.1/report.schema.json).

<a id="DDK-RESULT-001"></a>
### DDK-RESULT-001 — Four check outcomes

Every check instance MUST have exactly one status:

| Status | Meaning |
| --- | --- |
| `passed` | The named check established its stated relation within its declared scope. |
| `failed` | The named check established a contradiction or violated a required rule. |
| `unknown` | The check was attempted but available information or supported reasoning could not decide it. |
| `not_run` | The check did not run, for example because a prerequisite failed or a required adapter is absent. |

Each instance MUST identify its requirement, group, subject, required/applicable flags, and evidence level. `unknown` and `not_run` MUST include a reason. A result with `applicable: false` MUST use `not_run` and explain why. It does not block the overall decision.

<a id="DDK-RESULT-002"></a>
### DDK-RESULT-002 — Overall decision

The report MUST compute `decision` in this order:

1. `error` when an operational failure prevents a trustworthy run or required report completion.
2. Otherwise, `failed` when any applicable required check failed, or a declared warnings-as-errors gate failed.
3. Otherwise, `incomplete` when any applicable required check is `unknown` or `not_run`.
4. Otherwise, `passed`.

Optional failed checks MUST remain visible, even when they do not gate the decision. A passed decision MUST state the requested and completed profiles; it MUST NOT be summarized as proof that all implementations or datasets are correct.

<a id="DDK-RESULT-003"></a>
### DDK-RESULT-003 — Diagnostics

Every diagnostic MUST have a stable code, severity, message, and subject location. Related locations SHOULD identify the declaration responsible for a call failure. A checker MUST sort diagnostics by normalized source path, JSON Pointer, code, and check identity. Changing display verbosity or severity filters MUST NOT change the underlying results or exit code. Suggested fixes MUST be presented as suggestions, not applied automatically.

<a id="DDK-RESULT-004"></a>
### DDK-RESULT-004 — Evidence and coverage

A report MUST contain the loaded scope, requested check groups, available and missing adapter capabilities, mapping limits, dependency versions, and lock state. Evidence MUST distinguish authored claims, static inferences, and observed test results. Runtime evidence MUST identify its data snapshot. A report consumer MUST preserve unknown and not-run states rather than reducing every non-failure to success.

Executed passed or failed checks MUST attach at least one `evidenceRecords` entry. File evidence MUST identify kind, path, and SHA-256 digest of its actual bytes. Native dataset evidence for execution profiles MUST identify kind and an immutable `nativeVersion` using its reference scheme and native digest algorithm. Catalog observations can instead cite scheme-qualified exact references under DDK-CATALOG-003 and the underlying check records. Native reports, implementation artifacts, plans, fixtures, and dataset snapshots use separate entries as applicable. A native identity MUST NOT be relabeled as an artifact SHA-256 digest. Impact reports MUST populate the structured `impact` section with base/candidate projects, changed identities, and affected-consumer paths. Free-text summaries alone do not satisfy that structure.

<a id="DDK-RESULT-005"></a>
### DDK-RESULT-005 — Initial diagnostic families

A checker MUST classify initial diagnostic codes in these families: `DOC` for syntax and versions; `REF` for references and imports; `CALL` for interfaces and arguments; `DATA` for compatibility; `GRAPH` for step relationships; `POLICY` for project rules; `IMPACT` for changes; `LOCK` for inventory mismatches; `ADAPTER` for capabilities; `EXEC` for execution evidence, and `CATALOG` for product, relationship, version, discovery, and lineage diagnostics. Codes MUST NOT be reused with a different meaning within specification version 0.1. The conformance suite records the precise codes required for its cases.

### 13.1 Illustrative diagnostics (informative)

```text
CALL-ARGUMENT-UNKNOWN: design revenue, step read-orders supplies region;
the selected reader declares country instead.

DATA-NULLABILITY: customers.customer_id permits null values;
the enrich input requires a non-null customer_id.

ADAPTER-CAPABILITY-UNKNOWN: plan output comparison was requested;
the tax component has no supported plan implementation.
```

<a id="DDK-RESULT-006"></a>
### DDK-RESULT-006 — Runtime outcomes and uncertain responses

Reports MUST keep check status separate from runtime execution and selection outcomes. Each submitted request MUST have an `operations` record identifying runtime, mode, request identity, known outputs, execution outcome, selection outcome, and reconciliation capability. Managed requests MUST record their original native operation ID before submission in a caller-owned request artifact or native protocol that remains recoverable after caller restart; a lost response MUST retain that ID for reconciliation. This does not require a DDK lifecycle database. A timeout or cancellation request MUST NOT establish that execution stopped, failed, or never began. Unknown execution or selection MUST include a reason. An empty observed-output list under uncertainty MUST NOT establish that no outputs exist. Resubmission under the same operation ID is permitted only under the runtime's idempotency guarantee; uncertainty MUST NOT automatically allocate a replacement operation. Bounded jobs MUST NOT claim durable reconciliation without an explicitly qualified tracking capability. A selected outcome MUST identify the exact candidate; quality-gated selection MUST also identify the runtime-accepted qualification. Caller-produced report validity alone MUST NOT establish runtime acceptance. Existing decision and exit-code precedence remains unchanged: an operational error can coexist with an unknown native outcome.

Execution `pending` means the native owner admitted the operation and confirms that computation has not started. It MUST remain distinct from `not_submitted`, `running`, and `unknown`. Recovery MUST compare the complete original prepare request when available, and preserve any supplied native request and candidate constraints without treating an intended candidate as observed. A later command timeout or refusal MUST NOT erase a confirmed historical selection or its accepted qualification. Historical selection does not establish that the candidate is still the current selection.

A native publication-intent action MUST use the `publicationIntent` report variant. It records a saved delivery decision, with computation and selection both `not_requested` and no data outputs or job-qualification claims. The command's request identity, native intent identity, and original producing-job identity MUST remain distinct. A verified native reference MUST preserve its table incarnation and record generation. `succeeded` requires a pinned native observation and explicit `retained` or `retired` payload state. An unbound inspect MAY report a pinned `not_found` observation; absence MUST NOT erase a previously verified saved decision. A later unconfirmed or refused refresh MAY preserve that historical identity, but its current payload state MUST be `unknown`. A lost initial freeze MUST be reconciled by replaying the exact original request unless an independently known native reference can constrain inspection. Saving the intent MUST NOT establish external authorization, dispatch, or publication.

<a id="cli"></a>
## 14. Command-line behavior

The executable name is `ddk`. The source implementation exposes these commands; the [implementation status](implementation-status.md) records their tested coverage.

<a id="DDK-CLI-001"></a>
### DDK-CLI-001 — Core commands

An initial CLI MUST expose `check`, `impact`, `lock`, `build`, `test`, and `catalog`. `catalog` resolves product definitions and explicit native metadata inputs, then writes the requested catalog outputs and check report. `check` defaults to `core`. `impact` adds the impact profile and requires explicit base and candidate projects. `build` generates explicitly requested supported artifacts. `test` executes only explicitly selected tests and bindings. The default command path MUST NOT run ingestion or production transformations. Core invocation MUST accept a project path, optional lock path, `--locked`, output format, selection filter, and explicit additional permitted roots.

<a id="DDK-CLI-002"></a>
### DDK-CLI-002 — Exit codes

The CLI MUST return `0` for `passed`, `1` for `failed`, `2` for `incomplete`, and `3` for `error`. Invalid command usage MUST return `64`. Known malformed documents are check failures, not operational crashes. Unreadable required files, adapter process crashes, and resource exhaustion that prevent trustworthy completion are operational errors. The precedence in Section 13 determines the code when several conditions occur.

<a id="DDK-CLI-003"></a>
### DDK-CLI-003 — Machine output

`--format json` MUST write exactly one report object to standard output and send progress or logs to standard error. Human and JSON formats MUST express the same results and decision. When a command encounters an operational error after selecting JSON output, it SHOULD emit a valid error report where possible. Writing reports and generated bundles to files MUST be atomic; a failed command MUST preserve existing successful artifacts.

<a id="DDK-CLI-004"></a>
### DDK-CLI-004 — Explicit requested coverage

Commands MUST allow additional required check groups without editing project files. Command additions MUST NOT remove mandatory core groups. A missing requested adapter MUST yield required `not_run` results and exit `2`, not an implicit fallback. A build that supports only part of an explicitly requested export set MUST NOT claim a complete bundle or overwrite a previously complete one.

### 14.1 Illustrative commands (informative)

```sh
ddk check examples/commerce/project.ddk.json --format json
ddk lock examples/commerce/project.ddk.json --output project.ddk.lock.json
ddk check examples/commerce/project.ddk.json --locked --lock project.ddk.lock.json
ddk impact --base base/project.ddk.json --candidate candidate/project.ddk.json
ddk build examples/commerce/project.ddk.json --require plan.output --output build/revenue
ddk test examples/commerce/project.ddk.json --bindings examples/commerce/bindings.ddk.json --require test.fixtures
ddk catalog examples/commerce/project.ddk.json --metadata examples/commerce/catalog/metadata.example.json --metadata-adapter example-commerce-metadata --current-selection https://data.example.org/commerce public-revenue --export dcat --export openlineage --output build/catalog
```

<a id="integrations"></a>
## 15. Integration profiles

The detailed profile boundaries in [adapter-profiles.md](adapter-profiles.md) implement the requirements below. Their examples and version research are informative; explicitly numbered adapter requirements here are normative.

| Profile | Check groups | Principal evidence |
| --- | --- | --- |
| `core` | Six mandatory `core.*` groups | Declared |
| `impact` | `impact.consumers`, `impact.compatibility`, `impact.non-weakening` | Declared/inferred |
| `catalog` | `catalog.definitions`, `catalog.relationships`, `catalog.versions`, `catalog.evidence` | Declared definitions and cited native observations |
| `catalog.dcat` | `catalog.dcat` | Generated DCAT 3 discovery and checked access links |
| `lineage.openlineage` | `lineage.openlineage` | Declared job events and observed run events |
| `odcs-cli` | `odcs.lint`, `odcs.versions`, `data.odcs` | Declared or executed, depending on command |
| `files.frictionless` | `files.structure`, `files.constraints` | Executed |
| `ingest.dlt` | `ingest.schema-policy`, `ingest.receipt` | Declared/executed |
| `plan.docspec-sql` | `plan.compile`, `plan.output` | Inferred from SQL through DocSpec |
| `execute.docspec-job` | `runtime.job` | Executed; bounded job, no implied durable recovery |
| `runtime.docspec-managed` | `runtime.managed`, `runtime.qualification` | Executed; qualified operation/backend pairs only |
| `plan.datafusion` | `plan.compile`, `plan.consumer`, `plan.output` | Inferred from saved Substrait through DocSpec |
| `plan.substrait-validator` | `plan.standard` | Inferred, bounded by validator coverage |
| `test.fixtures` | `test.fixtures` | Executed |
| `test.portability` | `test.portability` | Executed on identified engines |

<a id="DDK-ADAPTER-001"></a>
### DDK-ADAPTER-001 — Capability manifests

An adapter MUST publish a manifest conforming to [adapter.schema.json](../schemas/0.1/adapter.schema.json), naming its version, profiles, check groups, supported input standards and versions, mapping limitations, dependency versions, and evidence references. Execution capabilities MUST additionally name artifact formats, execution mode, backend, request kinds, and reconciliation support. Native-reference and quality-access support MUST be claimed separately. Installed executable code MUST NOT be imported merely to discover capabilities during a core check. A capability advertised as qualified MUST be backed by passing independent conformance cases for the claimed version tuple. An `experimental-unverified` manifest describes an experiment candidate and MUST NOT populate the report's qualified available capabilities.

<a id="DDK-ADAPTER-002"></a>
### DDK-ADAPTER-002 — Mapping coverage

For every requested dataset translation, an adapter MUST report each required facet as `exact`, `checked`, `unsupported`, or `unknown`. `exact` means the target declaration preserves the facet; `checked` means a separately identified executed test checks it rather than encoding it in the target schema. Uniqueness, nullability, missing-value handling, decimals, time zones, enums, and nested structures MUST be accounted for explicitly when present. A mapping entry or emitted configuration alone MUST NOT establish semantic support.

<a id="DDK-ADAPTER-003"></a>
### DDK-ADAPTER-003 — ODCS and shared definitions

The initial ODCS adapter MUST use the public ODCS 3.2.0 schema and preserve Data Contract CLI's documented local-definition semantics. Runtime quality and version checks MUST retain their engine, dialect, selected perspective, and underlying diagnostics. Network resolution MUST remain disabled for offline checking. A quality rule that the selected backend cannot execute MUST not be counted as a successful data test.

<a id="DDK-ADAPTER-004"></a>
### DDK-ADAPTER-004 — Files and ingestion

The Frictionless adapter MUST keep structural file checks separate from transformations and preserve its missing-value and constraint semantics. The dlt adapter MUST distinguish column declarations from schema-evolution policies and MUST identify the dataset stage to which each applies. A discard policy MUST record discarded counts when available and MUST NOT claim to have quarantined rows unless an explicit implementation saved them. Staged outputs MUST be associated with the load identifier and exact snapshot used by subsequent checks.

<a id="DDK-ADAPTER-005"></a>
### DDK-ADAPTER-005 — Substrait production and consumption

An adapter claiming Substrait support MUST identify its authoring input, producer version, encoded Substrait version, function-extension identifiers and algorithm-tagged digests, consumer version, and supported operations. DataFusion through DocSpec is the initial proposed producer and consumer. Tests claiming Substrait execution MUST consume the saved plan bytes rather than rerun original SQL. Ordinary SQL preparation and execution MUST NOT require a Substrait intermediate or imply Substrait support. Logical input bindings MUST resolve before consumer planning. Field order, names, nullability, and physical-type mappings MUST be explicit.

<a id="DDK-ADAPTER-006"></a>
### DDK-ADAPTER-006 — Independent plan checks

`plan.compile`, `plan.consumer`, `plan.standard`, and `plan.output` MUST be separate check groups. Successful consumer planning MUST NOT be reported as successful standalone Substrait validation. A validator's loose mode MUST NOT convert indeterminate validity into a passed DDK standard check; unresolved validity MUST remain `unknown`. Unsupported format versions MUST NOT trigger silent conversion or downgrade. A required unavailable compatible validator MUST yield an incomplete result.

<a id="DDK-ADAPTER-007"></a>
### DDK-ADAPTER-007 — Fixture and portability testing

Fixture tests MUST specify independently authored input rows, expected outputs, dataset bindings, implementation format, and comparison rules. SQL fixtures MAY execute the identified SQL artifact directly; Substrait fixtures MUST consume the identified saved bytes. Unless specified otherwise, rows are compared as an unordered multiset, preserving duplicates; column names and values are compared exactly. Numeric tolerances, sort keys, and null behavior MUST be explicit. Portability tests MUST consume the same saved plan on at least two identified engines, compare each result with independent expectations, and name the tested operation subset. Agreement between two engines alone MUST NOT establish correct business results.

<a id="DDK-ADAPTER-008"></a>
### DDK-ADAPTER-008 — Execution boundary

Execution adapters MUST run only after explicit invocation of an execution profile with explicit bindings. Readers, SQL, custom functions, policy executables, and ingestion implementations are executable code, not ordinary document parsing. A custom function declaration MUST NOT be treated as an implementation. Fixture execution MUST default to local test data and a temporary output location. Publication or changes to production destinations require a separate caller-controlled workflow; a passed DDK report MUST NOT publish automatically.

<a id="DDK-ADAPTER-009"></a>
### DDK-ADAPTER-009 — Generated bundles

A successful build MUST produce a manifest conforming to [bundle.schema.json](../schemas/0.1/bundle.schema.json), identifying source document digests, requested exports and their implementation artifacts/formats, generated job or plan and configuration digests where applicable, logical input schemas, native inputs where used, mapping coverage, adapter versions, and missing obligations. An SQL export MUST NOT require a fictitious saved plan. Generated ODCS views MUST retain source provenance and distinguish inherited content from derived runtime configuration. They MUST NOT masquerade as independently published versions of the original dataset definition. A consumer MUST be able to verify the bundle before using cached results.

<a id="DDK-ADAPTER-010"></a>
### DDK-ADAPTER-010 — Bindings and fixture values

Bindings MUST follow [bindings.schema.json](../schemas/0.1/bindings.schema.json), resolve their design and origins, and choose exactly one data kind: `files` or `native`. File bindings MUST verify every supplied file digest before execution; native bindings MUST follow DDK-ADAPTER-012. Duplicate bindings for one origin MUST fail. A supplied binding for a reader's output is an injected dataset and MUST NOT be reported as execution of that reader. Fixture rows MUST follow [fixture.schema.json](../schemas/0.1/fixture.schema.json) and be converted using explicit input mappings; scalar dates use ISO calendar-date strings, numeric tolerances default to zero, and unsupported temporal or decimal conversions MUST remain unknown. Each expected output MUST name an existing output port. Fixture data and binding paths resolve from their declaring files. Binding `execution` settings are operational configuration, not component meaning; adapter-owned connection and limit shapes MUST be checked by the explicitly selected profile. Managed execution settings MUST identify `operationId`, `requestKind`, and `qualificationRequired`; required qualification MUST also identify the resolved `rules` artifact. Equivalent caller configuration MUST preserve the same information before submission. These settings do not authorize an unsupported request kind or production selection.

<a id="DDK-ADAPTER-011"></a>
### DDK-ADAPTER-011 — Execution responsibilities and modes

Execution integration MUST distinguish preparation, bounded execution, managed dataset operations, and quality evaluation. The initial application ports are `PlanService`, `JobExecutor`, and `QualityEvaluator`; `DatasetRuntime` MUST be introduced with the first managed workflow. A concrete adapter MAY implement several ports. Preparation MUST report inferred schemas and support without production-row scans. Bounded jobs MUST report known completed outputs on a returned partial failure without implying durable recovery. Managed capabilities MUST identify tested request kinds and backends, preserve stable native operation identity, and reconcile through the native runtime. DDK MUST NOT duplicate runtime phase state, retry decisions, retention authority, or selection authority. Ordinary SQL jobs MUST NOT silently become managed operations. These ports do not require separate servers or a universal calculation representation.

<a id="DDK-ADAPTER-012"></a>
### DDK-ADAPTER-012 — Exact native dataset access

A native binding MUST identify runtime, reference scheme and version, namespace, digest algorithm, and the unmodified native reference. The selected profile MUST validate the native reference shape and resolve an exact read view preserving consumed version, schema interpretation, native field IDs, and explicit name/order/type mappings. Its receipt MUST record those observations in `nativeReads`; declaration alone MUST NOT count as observed native access. Core MUST check only the wrapper and declared scheme support without contacting the runtime. A runtime MUST protect required inputs/candidates for the operation's lifetime and report unavailable protection or data explicitly; a captured identity alone does not establish availability. Missing data MUST NOT fall back to latest. An adapter MUST NOT export and reimport a native dataset merely to cross the DDK boundary. Explicit file exports remain separate artifacts with their own identities. A scheme using unsupported or mixed native digest algorithms MUST remain unsupported until its profile and representation are specified.

The explicitly selected `urn:ddk:docspec:source-arrow:2` read profile records the complete canonical **public source view**, including nested structs and list items, in the unchanged Arrow schema emitted by the native owner. Its separate field index MUST cover every observed node, preserve sibling position and the full field-ID path, and reject absent, duplicate or invalid native IDs, duplicate sibling names, incomplete children and unsupported types. Types, units, timezones, precision, scale, nullability and metadata belong to the captured schema; the index MUST NOT repeat or reinterpret those values. The profile supports the canonical source types stated by its maintained adapter, with explicit limits on schema depth and field count. It MUST NOT infer original integer widths, original timezones, UUID meaning from fixed-width binary, a physical table/snapshot identity, or a broader computed/group view. Its source-schema identity combines the exact VersionRef manifest digest with the observed schema ID and is not a full physical-view identity. Original declarations and native normalization provenance remain separate evidence. The unchanged v1 flat record remains interpretable as v1; v2 requires its explicit profile discriminator, so an older schema refuses it instead of interpreting a partial flat mapping as complete. Neither read profile establishes logical-option validation or candidate qualification by itself.

This v2 profile permits at most 16 field levels (roots count as level 1), 4,096 total nodes, 1,024 UTF-8 bytes per field name and 2 MiB for the complete field index encoded with the shared JSON serializer. These bounds apply before accepting the observation. The field-depth limit fits the existing receipt JSON nesting limit. Streaming completion additionally checks the exact recursive schema against the IPC schema with metadata, the complete row count, stream digest, EOF and successful child exit. Capacity, early close, malformed receipts and unsupported shapes do not establish a completed native read.

<a id="DDK-ADAPTER-013"></a>
### DDK-ADAPTER-013 — Qualification before managed selection

A quality evaluator MUST identify the exact candidate, complete resolved rule-set artifact and digest, evaluator version and development build identity, evaluation/mapping semantics, required check IDs, per-check outcomes, and native evidence. Rule-set artifacts MUST include followed definitions, effective rule parameters, and required coverage. Duplicate check IDs, missing required checks, failed, unknown, or not-run required results MUST prevent acceptance. Report consumers MUST NOT equate a well-formed `qualifications` record with runtime acceptance.

When quality gates selection, the native runtime MUST retain the candidate, accept evidence from the configured evaluator under a validated candidate/rule binding, and check accepted qualification with applicable authority conditions in the guarded selection decision. The admitted request MUST capture required rules and applicable policy preconditions; policy changes MUST NOT silently mutate it. A changed qualification request MAY reuse the same computed candidate under DDK-LOCK-005. Evidence for another candidate, rule set, or evaluator semantics MUST NOT qualify this selection. Checking a selected version afterwards is audit evidence, not a pre-selection gate. An unavailable exact-native quality bridge MUST leave that capability unqualified; file-backed success alone MUST NOT establish it. DDK MUST NOT add a generic validation framework or select the candidate itself.

<a id="DDK-ADAPTER-014"></a>
### DDK-ADAPTER-014 — Shared runtime guards for calculation formats

SQL and Substrait execution through DocSpec MUST use its admitted runtime context and applicable memory, spill, concurrency, function, and input-binding checks. Decoded Substrait MUST pass normalized-plan checks before execution; bypassing SQL parsing MUST NOT bypass equivalent execution restrictions. Unsupported functions, external reads, statement effects, or mappings MUST be refused or reported unsupported before effects. The adapter MUST identify the tested runtime/producer/consumer tuple and preserve unknown standard validity separately from consumer support. Memory claims MUST state whether limits cover engine-managed resources or the whole process. Updating DocSpec's unreleased API or dependency baseline is permitted, but a new tuple MUST be qualified before support is claimed.

<a id="security"></a>
## 16. Security, privacy, and resource limits

<a id="DDK-SAFE-001"></a>
### DDK-SAFE-001 — Offline and file boundaries

Core checking MUST disable network access by policy and MUST never dereference an identifier merely because it is a URL. Only explicitly registered artifacts, followed allowed references, and pinned schemas may be read. Permitted roots default to the real directory of the root project; additional roots MUST come from caller configuration, not an untrusted imported document. Escaping symlinks, disallowed file schemes, and unsupported remote references MUST produce explicit diagnostics.

<a id="DDK-SAFE-002"></a>
### DDK-SAFE-002 — Execution and secrets

A checker MUST NOT evaluate template expressions, Python object constructors, shell substitutions, or arbitrary import hooks while reading documents. Execution adapters MUST receive argument arrays or structured API values rather than concatenated shell commands. Credentials MUST be supplied through an explicit runtime mechanism and MUST be excluded from published reports, bundles, and locks. Source snippets containing designated secret arguments MUST be redacted.

<a id="DDK-SAFE-003"></a>
### DDK-SAFE-003 — Limits and cancellation

A checker MUST enforce configurable limits for document bytes, total project bytes, reference depth, parsed nesting, artifact count, graph edges, adapter runtime, and captured diagnostics. Initial defaults are 8 MiB per document, 64 MiB of authored project input, reference depth 32, nesting depth 64, 10,000 artifacts, and 100,000 step edges. Pinned upstream schemas are tracked separately from the authored-byte limit. Limits and overrides MUST appear in the report. Exhaustion MUST preserve partial diagnostics and produce an operational error, never a truncated success. Adapters MUST support cancellation requests and bounded log capture. They MUST distinguish stopping the caller's wait from confirmed native cancellation and preserve uncertain outcomes under DDK-RESULT-006.

<a id="DDK-SAFE-004"></a>
### DDK-SAFE-004 — Data lifetime

Fixture runners MUST clean up their own temporary successful-run data and MUST preserve failure evidence when configured, identifying its location and sensitivity. Runtime adapters SHOULD process the selected staged snapshot directly rather than make unnecessary full copies. Cached evidence MUST retain its input digests and MUST expire when its validity conditions change. Performance claims MUST identify measurements and the tested environment.

<a id="versioning"></a>
## 17. Versioning and extensibility

<a id="DDK-VERSION-001"></a>
### DDK-VERSION-001 — Version boundaries

`specVersion: 0.1` fixes document semantics within this draft series. Artifact `version` tracks the author's declaration independently. ODCS and ODPS versions, DCAT and OpenLineage specification versions, JSON Schema dialects, Substrait versions, adapter versions, and engine versions MUST remain separately represented. A tool MUST NOT infer one from another. Unsupported mandatory versions MUST be reported explicitly.

<a id="DDK-VERSION-002"></a>
### DDK-VERSION-002 — Extensions

DDK document extensions MUST live in the `extensions` object, keyed by an absolute URI. An extension that changes required validation behavior MUST be named in requested capabilities. Unknown optional extensions MUST be preserved without affecting core outcomes. New adapters MUST use explicit manifests; installation alone MUST NOT enable execution or change existing results.

<a id="DDK-VERSION-003"></a>
### DDK-VERSION-003 — Profiles and release claims

A release MUST publish its supported profile matrix, exact dependency tuples, conformance results, and unresolved limits. The first DDK product release MUST qualify `core`, `impact`, `catalog`, `catalog.dcat`, `lineage.openlineage`, `odcs-cli`, `plan.docspec-sql`, `execute.docspec-job`, `plan.datafusion`, and `test.fixtures`. It MUST demonstrate ODPS resolution, DCAT discovery, OpenLineage design and run events, and execution of saved Substrait bytes. Users MAY install or invoke the offline checker independently. File intake, dlt ingestion, standalone Substrait validation, managed selection, and additional-engine portability qualify separately. An experimental capability MUST be reported with its actual coverage.

<a id="evidence"></a>
## 18. Conformance evidence

<a id="DDK-TEST-001"></a>
### DDK-TEST-001 — Independent expectations

A conformance claim MUST identify the requirement IDs and independently written cases it satisfies. Test expectations MUST come from this specification, public standards, or explicitly authored business examples. They MUST NOT be generated from the checker or transformation under test. Negative cases MUST verify both the diagnostic and the decision. Cases whose behavior is indeterminate MUST verify `unknown` and its effect on required coverage.

<a id="DDK-TEST-002"></a>
### DDK-TEST-002 — Required case families

A core checker MUST pass the core families in [cases.json](../conformance/cases.json): syntax, namespace resolution, imports, interfaces, parameter containment, dataset compatibility, multiple exports, policy references, lock verification, result aggregation, and execution isolation. An impact analyzer MUST additionally pass shared-interface and shared-definition change cases. Each claimed catalog or integration profile MUST pass its listed cases for the published tuple. Documentation-shape validation MUST NOT be reported as any of these runtime passes.

<a id="DDK-TEST-003"></a>
### DDK-TEST-003 — Release evidence

A release evidence bundle MUST include tool and dependency versions, test-case results, requested profiles, unknown/not-run inventory, fixture provenance, and measured resource results. Runtime claims MUST be reproducible from the released code and pinned public dependencies. A draft document or schema alone MUST NOT claim to be a conforming implementation.

<a id="DDK-TEST-004"></a>
### DDK-TEST-004 — Local stack demonstration

The first product release MUST demonstrate a connected local reference workflow using independently authored bounded inputs and expected rows. Resolve its ODPS product and ODCS datasets, check the design and the impact of a definition change, and bind a transformation to exact inputs. Execute SQL and replay the saved Substrait bytes through the qualified DocSpec path; compare each result with the independent expectations. Apply supported ODCS checks to the exact saved-plan output. Generate DCAT discovery and OpenLineage observations from actual retained execution and check records. A reader MUST use the generated DDK catalog to resolve that output before running a checked query. The evidence MUST form one connected path from input to reader.

Independent companion cases MUST cover nested/list paths, native binary values, composite keys, release-scoped identities, declared versus observed lineage, and version-bound checks. Wrong versions, incomplete keys, and missing required evidence MUST fail or remain incomplete as applicable. An unchanged metadata refresh MUST preserve reproducible outputs without reopening data payloads or rerunning their checks. A definition change MUST identify affected consumer outputs and check obligations.

When intake or ingestion is claimed, the workflow MUST pass the exact staged file inventory to execution. Managed qualification remains a separate typed operation/backend demonstration under DDK-ADAPTER-013, including exact protected candidate access, accepted evidence, guarded selection, reuse, and lost-response reconciliation. Project pilots, incumbent replacement, production publication, and maintenance removal are not prerequisites for this local demonstration.

### 18.1 Reference workflow scope (informative)

The [adopted build strategy](build-strategy-without-pilots.md) defines the local commerce workflow, a companion nested-data fixture, and the separate managed demonstration. [Deferred pilot notes](pilot-adoption-notes.md) retain future adoption work outside the current build.

<a id="catalog"></a>
## 19. Data product catalogs

Catalogs connect declared product meaning to exact data and evidence. The [catalog schema](../schemas/0.1/catalog.schema.json) defines the generated DDK catalog and the `project.catalog` configuration. Native manifests and receipts enter through explicit adapters. The generated catalog is a view of those inputs.

<a id="DDK-CATALOG-001"></a>
### DDK-CATALOG-001 — Fact ownership and scope

A catalog MUST identify the project revision, loaded definitions, exact source records, and adapter versions used to assemble it. References within the catalog MUST resolve to unique records within the declared scope or retain an explicit unresolved diagnostic. Maintained definitions own intended meaning and behavior. Acquisition records own capture and occurrence facts. Native execution and storage records own execution and retained-version facts. Publication records own release membership and selection. The catalog MUST cite the owner of each observed fact and preserve unresolved references and scope limits. Conflicting claims from the same authority for the same identity MUST produce a diagnostic. Claims from distinct scopes MUST remain distinguishable.

When retaining project extensions, keep each declaring project's identifier, exact version, import namespace, and namespaced values together. Assembly MUST NOT merge values from different declaring scopes or infer domain behavior from an unrecognized extension.

<a id="DDK-CATALOG-002"></a>
### DDK-CATALOG-002 — ODPS product and port resolution

The catalog profile MUST validate registered ODPS documents as `apiVersion: v1.1.0` against the [pinned ODPS schema](../vendor/odps/1.1.0/odps-json-schema-v1.1.0.json). It MUST use absolute product identifiers, an explicit product `version`, and exact `contractId` and `version` values for participating ports. At least one output port MUST participate. Resolve a port to a unique registered ODCS object with the matching contract ID and version. When a contract contains multiple registered objects, `project.catalog.ports` MUST select one by product alias, direction, port name, and port version. An explicit selection MUST match the port's contract ID and version. Ambiguous, duplicate, or mismatched bindings MUST fail. Product port versions identify definitions. Native data versions come from observations. Each product record MUST carry the ODPS `name`, `type`, `domain`, `status`, `description` (`purpose`, `usage`, `limitations`), and `context` its document declares, copied exactly; custom types keep their authored value.

<a id="DDK-CATALOG-003"></a>
### DDK-CATALOG-003 — Dataset, source, and exact version identity

Every dataset included in a catalog MUST have a `catalogId` that identifies its logical meaning across definition revisions. A generated definition MUST record the ODCS contract ID, version, selected object, and original document digest.

A dataset record MUST carry its registration's `role` and `attribution`, its contract's `status`, and its selected object's `description`, `tags`, `context`, and `canonicalUrl` links. Its `contract` block MUST carry the contract-level `description` (`purpose`, `usage`, `limitations`), `context`, `tags`, `canonicalUrl` links, and the `slaProperties` entries that apply to the selected object, each copied exactly. A context string is ODCS shorthand for `{instructions}` and is recorded in that form. An SLA entry applies when it names no element, after the deprecated `slaDefaultElement`, or when one of its comma-separated elements names this object by shorthand `name` or `name.property`, or by a `schema/<id>` path. Entries that name only other objects are omitted. An element DDK cannot interpret attaches to no dataset and MUST produce an optional `unknown` result.

`attribution.assertedBy` says who asserts the content: `publisher`, the original publisher of the records; `third_party`, another outside party; or `project`, the maintaining project. `attribution.derivation` lists how content was derived from its inputs: `deterministic` code, a `model` (statistical, machine-learned, or generative output), or `human` judgement. Derived and application datasets that declare attribution MUST list a derivation; retained originals MUST NOT. Content from a dataset whose derivation includes `model` MUST NOT be presented as a publisher's assertion. A version MUST identify the applicable definition and an exact native reference with its scheme, authority, and opaque native value. The scheme owns value interpretation and any digest or field identity it supplies. Opaque identifiers MUST retain their native meaning. A representation MUST identify the exact version to which it applies. Source occurrences MUST be distinguishable from content objects and from interpretations or corrections. A dataset version MUST link known source occurrences where the native records establish the association. An original MAY be represented by an occurrence and retained-content reference when a tabular definition does not apply.

A catalog-only mapping of a native table MUST preserve the original table identity, metadata location and byte identity, selected snapshot including an explicit empty selection, and schema identity. Its source-version identity MUST exclude local aliases, operation IDs and retained-copy locations. Native schema observations and custody evidence MUST remain attributable to each original run. A catalog reference alone MUST NOT imply runtime resolution, current retention, producer qualification or an available representation. The [local native-table mapping](catalog-api.md#native-table-catalog-observations) defines the existing adapter's scheme interpretation.

<a id="DDK-CATALOG-004"></a>
### DDK-CATALOG-004 — Faithful descriptions and scoped relationships

Catalog descriptions MUST preserve nested paths, list element traversal, meaningful ordering, native binary types, composite keys, and virtual identities with their scope. They MUST distinguish source literals from documented conversions and corrections. Use supported ODCS references where they carry the required meaning. A project MAY add a typed relationship for missing semantics. Path segments MUST distinguish a literal field name from list element traversal. Relationships MUST identify endpoints, ordered key components, matching rules, cardinality, null handling, scope, resolution expectation, and meaning. A declared link and its measured resolution are separate records. Relationship self-links and cycles are valid. Release-local references MUST bind to the same exact release when resolved for use.

The initial shared match rule is `equal`. Pair components in declared order and require every component to match. Supported comparisons use exact integer values, identical Unicode code-point sequences for strings, identical bytes for binary values, and the same calendar day for date values in the same declared calendar. Preserve declared type and scope and require compatible types. Apply the declared null policy before comparison. `skip` yields no match for a pair with a null key component, `reject` treats that key as invalid, and `match` matches null only to null at the same component. Treat a missing path as unresolved unless the owning definition supplies its interpretation. Report unresolved null handling or unsupported types as `unknown`. A list traversal selects elements for comparison and retains occurrence context. Project-specific conversions, list overlap rules, and other comparison semantics use `project_rule` with an exact versioned rule reference. The offline checker MUST validate supported endpoints and key rules and report unsupported reasoning as `unknown`. A supported comparison describes expected behavior. It takes executed evidence to establish actual matches or cardinality.

An external endpoint MUST retain its external identifier and declared resolution meaning. It does not become a local dataset alias or authorize fetching the target. The shared checker MUST retain an unsupported external comparison as `unknown`. Several identities MAY use the same virtual field when its path, type, and scope agree; conflicting meanings MUST fail resolution.

A declared `row_position` identity MUST participate in complete-key reasoning within its same-release scope, including when other physical keys exist. It MUST NOT require a duplicate `key` declaration on the same virtual field. This reasoning MUST NOT establish actual row positions, uniqueness, or relationship matches.

A programmatic catalog assembler MAY receive an explicitly supplied relationship profile for declaration reasoning beyond the shared rules. DDK MUST retain its own path, key completeness, key order, scope, supported-type, and null-policy checks before invoking that profile. Equal endpoint arity and pairwise shared comparison types apply to `equal`; a `project_rule` profile MUST assess its declared matching shape, including different source and target component counts. The profile MUST receive isolated immutable declarations and resolved key definitions, and return supported, failed, or unknown reasoning with a reason. Missing support, unsupported exact rule versions, malformed results, and profile errors MUST preserve uncertainty. The profile MUST NOT establish observed matches, cardinality, external target existence, or qualification from declarations alone.

The selected profile MUST identify its exact tool revision and either captured local source bytes or an exact source/distribution pin. Catalog and lock provenance MUST retain that identity and any captured source digest. A supplied source file identifies those bytes; it does not prove the callable's correspondence to them or its dependency closure. Core checks MUST NOT discover, import, or invoke such implementations. Public output MUST require explicit disclosure of the selected profile identity and apply the ordinary source/evidence disclosure rules.

<a id="DDK-CATALOG-005"></a>
### DDK-CATALOG-005 — Observed runs and version-bound evidence

The catalog MUST identify each included production definition and its declared input and output dataset definitions. The production reference MUST resolve to the selected component or design. The catalog MUST distinguish those declarations from the exact sources and versions observed in a run. An observed run MUST preserve its native operation reference, outcome, source record, and observed inputs and outputs. Record `inputCoverage` separately from execution outcome. `complete` requires native evidence that the recorded inputs exhaust the stated run scope. `partial` identifies a known incomplete set, and `unknown` records an unresolved claim of coverage. An empty input list with unknown coverage leaves consumption unresolved. Capture, retention, and availability observations establish only their own facts.

A check summary MUST identify the exact version, versioned rule, evaluator, checked scope, status, and underlying evidence or reason for its absence. Qualification MUST use the check reducer and requested coverage of Section 13. Required missing evidence MUST remain `unknown` or `not_run`. Catalog assembly MUST distinguish success at describing the supplied observations from qualification of the data for a requested purpose. A queryable dataset MAY remain visible with unresolved qualification. Reuse evidence only when target, rule, evaluator, scope, and original custody assumptions still apply. Preserve the assurance level of a presence check. Coverage observations MUST retain their units and scope. A complete or partial coverage count MUST identify its comparable expected population. Unknown coverage MAY report a known observed count.

A managed-job mapper MUST bind the exact captured production and dataset definitions to the original native request and account for every input and output within its stated scope. Native policy acceptance MUST NOT imply coverage of unrelated authored field rules. An explicitly supplied application generator MAY bind authored facets to exact original native reports. The mapper MUST reproduce those bindings from immutable captured definitions and original JobSpec bytes, verify exact accepted report membership and outcomes, and retain generator identity separately from evaluator identity. Missing support and changed or incomplete bindings MUST remain unknown. Metadata MUST NOT load generator code.

A nondefault managed output-schema interpretation MUST be selected explicitly
for each dataset it affects and included in the original captured definition
identity. The mapper MUST preserve the default interpretation for unselected
outputs and MUST NOT fall back when a selected interpretation is unsupported.
Type-representation options and row-value constraints MUST retain their distinct
evidence requirements. The explicit
[Arrow declaration observation profile](arrow-declaration-profile.md#observing-managed-output-schemas)
reuses the maintained declaration mapping; it does not execute value checks.

When the accepted policy ID is the original admitted policy ID, its policy bytes and authority conditions MUST agree with that original request. A distinct native requalification policy MAY change those conditions while retaining the original request unchanged. An incomplete native observation MUST NOT invent a binding to the current production definition.

Native output-schema facts, accepted row counters and supported export invariants MUST retain their distinct scope. Nonnull evidence MUST NOT imply uniqueness. Ordered-export uniqueness MUST cover the entire authored key under the exact supported native interpretation; a unique larger tuple MUST NOT qualify a subset. A composite nonnull claim MUST account for every key field in the same exact output. These facts MUST NOT replace required native policy acceptance or execution qualification.

<a id="DDK-CATALOG-006"></a>
### DDK-CATALOG-006 — Release composition, selection, and access

A release MUST name its native identity and exact version membership within the catalog's explicit scope. A selection MUST name its authority, purpose, observed time, and release. The catalog records publisher selections observed for the build. Retain historical membership as release records and keep previously resolved bindings with their original selection evidence. When a consumer uses a query or navigates a version-scoped relationship, its binding MUST identify the applicable selection record or explicit release and the exact dataset versions used. If the operation allows an explicit version pair, bind both exact versions and their applicable scope. Resolve the binding before use and report missing or ambiguous required inputs. A checked query MUST record the resolved binding with its result. A newer selection MUST leave previously observed run bindings and historical release membership intact.

Local release observations MUST contain their exact native reference. A public
view MAY withhold that reference while preserving an explicitly disclosed
release identifier and its disclosed version membership. Such a record MUST
contain `referenceDisclosure: "withheld"` and MUST NOT contain `reference`.
Only an explicit `nativeReferences` grant permits the reference. Removing any
member from a complete release MUST change its public membership to `partial`;
existing partial or unknown membership MUST NOT be upgraded. A public selection
still requires its disclosed authority and release. These disclosures MUST NOT
imply data access, native selection or publication authority.

Retention, successful parsing, qualification, representation availability, and selection MUST be reported from their respective evidence. A valid empty output, known absence, unresolved coverage, and acquisition failure MUST remain distinguishable. Supported query examples MUST identify their dialect, input datasets, parameter schema, and result grain or the dataset definition that owns that grain. Discovery MUST treat examples as documentation.

Recipes MAY carry a title, ordered notes, and `contextualRelationships` for explanatory links. Each contextual link MUST resolve to a declared relationship. It MUST NOT add an unread endpoint to the recipe's inputs or execution binding. When positional parameters are used, `parameterOrder` MUST name every parameter property exactly once in the intended order. Consumers MUST preserve that order and MUST NOT infer it from object keys or the schema's `required` array.

<a id="DDK-CATALOG-007"></a>
### DDK-CATALOG-007 — Local assembly and output integrity

The catalog command MUST take an explicit project and output set. It MUST support a definition-only build with no metadata adapter and no inferred availability. When supplied, `--metadata` names a local input and `--metadata-adapter` selects its reader. Each `--export` names a generated companion format. Adapters MUST read existing owner records where available and preserve their assurance and scope. Ordinary assembly MUST reuse admitted metadata without opening, rehashing, or copying data payloads or rerunning their checks.

Resolve authored recipe SQL against its declaring document. Publish each included recipe as a companion file with the original SQL bytes and a digest under `files`. The generated recipe's `sql` path MUST resolve relative to the catalog to that file. Its original source and digest MUST appear in the input inventory. Any other retained relative path MUST carry its resolution origin. Companion paths MUST resolve uniquely inside the output set. The public view MUST apply an explicit disclosure policy to SQL, locations, identifiers, and evidence links before writing them. A recipe whose SQL cannot be disclosed MUST be omitted from the public view with a diagnostic.

The disclosure policy shape is defined by `catalog.schema.json#/$defs/disclosurePolicy`. Public definition disclosure MUST name allowed field paths for each disclosed dataset. Retain only those fields, necessary structural ancestors, supported types and nullability, and explicitly allowed descriptions. A disclosure-only empty path MAY grant root metadata, including its description when descriptions are enabled; it MUST NOT grant child fields or native/custom properties. Identity and relationship paths MUST remain nonempty. Mark the disclosed paths so consumers can identify a partial definition. The root object name MUST follow the disclosed object identity. Unlisted siblings, private native references, and custom properties remain withheld. Public product and dataset records keep `type`, `status`, `role`, and `attribution`; their names, domains, descriptions, contexts, tags, and SLA entries require `descriptions: true`, and each canonical URL also requires its exact value in `locations`. Project extensions require an explicit grant for the source project's exact identifier and version and the selected extension namespaces; granting one scope MUST NOT merge it with another. An extension value is opaque: when a granted value names a withheld alias, namespace segment, object or port name, or record identifier, assembly MUST refuse the public view rather than edit the value.

An opaque composite `physicalType` MUST remain withheld unless `definitionPhysicalTypes` explicitly grants its nonempty field path. Each grant MUST identify a disclosed dataset, resolve to an existing nonblank native type, and require disclosure of the complete modeled subtree at that path. A parent grant alone MUST NOT grant descendants. Copy the original type string exactly; do not parse, normalize, or reverse-compile it. Explicit permission covers the entire opaque string, including native-only names that the logical definition does not model. Modeled coverage alone MUST NOT imply that permission or logical/native completeness. Declared objects and arrays remain composite even when their modeled children are absent. Root disclosure MUST NOT grant native type text. An incoherent type grant MUST fail disclosure and preserve the prior complete output set. Existing scalar type disclosure remains unchanged.

`logicalTypeOptions` MUST remain withheld unless `definitionLogicalTypeOptions` explicitly grants its nonempty field path. Options may contain patterns, bounds, time-zone details or required property names, including names absent from the modeled children. Each grant MUST identify a disclosed dataset, resolve to an existing options object, and require disclosure of the complete modeled subtree at that path. The grant permits the entire original options object; copy it exactly without defaults, filtering or coercion. An empty object remains an empty object. A root, structural-ancestor, description or physical-type grant MUST NOT grant these options, and a parent options grant MUST NOT grant its descendants. An incoherent grant MUST fail disclosure and preserve the prior complete output set. Disclosing options establishes their authored meaning, not native execution or quality-check support for them.

A programmatic assembler MAY return an admitted catalog and its exact companion bytes while required checks remain incomplete or failed. Their presence MUST NOT establish qualification or authorize publication. Preserve the report and every required outcome. Public results MUST filter both content and diagnostics for the requested audience, including failures before assembly. Complete publishable output sets MUST be available only for passing results. An optional filesystem writer MUST use the same admitted bytes and preserve the previous complete output set on failure.

An assembler MAY expose its full admitted metadata as explicitly private `local_catalog`, alongside the requested-audience catalog. Both MUST use the same captured source snapshot without another load or schema owner. Structural admission failure MUST leave the private catalog absent; unresolved qualification or a later disclosure failure MUST NOT turn that metadata into a passing result. Private metadata MUST NOT enter public companions or artifacts through this API.

An explicitly requested paired private output MUST reuse that same admitted snapshot and original companion bytes. It MUST remain absent unless all required checks and both standard output preparations pass. Its private lock extension `urn:ddk:catalog:paired-public-view:1` MUST contain exactly `catalog` (the unchanged catalog identifier), `publicLockSha256` (the exact public lock digest), and `datasets` (one `{id, publicAlias, localAlias}` entry per disclosed dataset, in public dataset order). This association MUST NOT enter public artifacts or imply data qualification. A paired reader MUST require external pins for both complete artifact sets and MUST verify the exact association and preserved version, representation, release membership/completeness, selection, named recipe-input and SQL identities. Private metadata MUST NOT authorize private fields through a public request. A data provider MUST enforce the public field scope independently of the paired catalog association.

The inventory MUST identify source definition bytes, native metadata inputs, audience policy, and mapping adapter identities. Identical inputs and mappings MUST produce reproducible catalog content and artifact digests. A successful build MUST inventory generated files and their digests and atomically replace the complete output set. Missing required formats MUST preserve the prior complete output set and follow DDK-CLI-004.

<a id="DDK-CATALOG-008"></a>
### DDK-CATALOG-008 — DCAT 3 discovery

A `catalog.dcat` producer MUST generate a DCAT 3 JSON-LD document with stable resource identifiers, datasets and their available versions, and supported distributions or data services. Version relationships MUST preserve the original identity and revision semantics. Access descriptions MUST reflect the exact representation and audience.

For a DCAT export, the caller MAY request `--current-selection <authority> <purpose>`. Record that choice as `currentSelection` in the generated catalog and catalog lock. For each dataset, use the publisher's supplied current selection records with that exact authority and purpose whose releases contain a version of that dataset. The adapter MUST distinguish those selections from historical release membership. A single matching selection with a single version permits `dcat:hasCurrentVersion` and MUST be cited. Omit the assertion when the caller supplies no selector or the dataset has no match. Multiple distinct matches or multiple versions in the matched release for that dataset MUST fail the requested DCAT export. Disjoint publisher selections can serve different datasets in one export. File order, observation time, and catalog generation MUST NOT break ties. Quality and provenance details MAY link to the DDK records that carry their full scope. Validation MUST use an independent JSON-LD reader and the DDK DCAT mapping cases.

<a id="DDK-CATALOG-009"></a>
### DDK-CATALOG-009 — OpenLineage design and run records

A `lineage.openlineage` producer MUST generate `JobEvent` records for declared production definitions and `RunEvent` records for supported, observed lifecycle events. Validate each against the [pinned event schema](../vendor/openlineage/1.55.0/OpenLineage.json). Preserve existing OpenLineage namespace and name pairs, run IDs, and native version facet values when the source identifies the same entity. For identities without existing OpenLineage records, use a deterministic adapter mapping following the supported data source's naming convention. Give distinct physical datasets distinct OpenLineage identities even when they share a logical catalog ID. Resolve or report conflicting mappings before emitting them. Repeated import of the same source event MUST preserve its identity.

Record the event run ID in `openLineageRunId`. The catalog and pinned mapping inputs MUST resolve event dataset identities and version facets to the exact known catalog versions and original native references. Use a catalog version ID in the version facet when no compatible native value exists. A generated job event MUST use an explicit time from its declared metadata input. Emit known consumed inputs only and retain input coverage in DDK alongside the event. An unresolved outcome MUST NOT generate a fabricated terminal event. A definition MUST NOT generate run evidence. Preserve partial lifecycle coverage and evidence omitted by the standard mapping with their original scope and result.

<a id="DDK-CATALOG-010"></a>
### DDK-CATALOG-010 — Catalog change analysis

An impact analyzer claiming catalog coverage MUST compare exact definition revisions, declared relationships, supported access, and requested policy rules for the loaded products. It MUST identify affected known consumers and check obligations and distinguish changes requiring computation, requalification, or metadata regeneration. A consumer or evidence scope outside the loaded inventory MUST remain explicitly unresolved.

Recipe titles, notes, and contextual links affect documentation and applicable reader checks. A contextual endpoint alone does not establish a computation dependency. If the same dataset is also a real input, retain the stronger input obligations. A change to a scoped extension requires metadata regeneration; unknown domain effects MUST remain unresolved rather than becoming a blanket computation invalidation.

Changes to a selected relationship profile's provenance or its declaration assessments MUST remain visible even when the relationship declarations are unchanged. Link those changes to the relationships actually assessed and their known readers. Require metadata regeneration and applicable reader checks, retaining unresolved domain effects without inferring a computation dependency.

Public filtering MUST retain permitted profile identity and redacted source provenance for comparison. Withheld assessments and consumer coverage MUST remain explicitly unknown; they MUST NOT become an empty, completed scope or fabricated reader dependencies.

<a id="references"></a>
## 20. References

### 20.1 Normative references

- [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119): requirement keywords.
- [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): uppercase keyword interpretation.
- [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259): JSON.
- [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901): JSON Pointer.
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12): DDK shapes and parameters.
- [JSON Schema Draft 2019-09](https://json-schema.org/draft/2019-09/schema): the pinned ODCS schema's dialect.
- [ODCS 3.2.0](https://github.com/bitol-io/open-data-contract-standard/tree/v3.2.0), its [pinned schema correction](https://github.com/bitol-io/open-data-contract-standard/commit/448f7b93329ece7827897d7dd51e827a3e279460), and the [vendored schema](../vendor/odcs/3.2.0/odcs-json-schema.json). The draft intentionally uses this development revision; it is not byte-identical to the published tag.
- [ODPS 1.1.0](https://github.com/bitol-io/open-data-product-standard/tree/v1.1.0) and its [pinned schema](../vendor/odps/1.1.0/odps-json-schema-v1.1.0.json).
- [DCAT 3](https://www.w3.org/TR/2024/REC-vocab-dcat-3-20240822/) and [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/).
- [OpenLineage 1.55.0](https://github.com/OpenLineage/OpenLineage/tree/1.55.0), the [event schema](../vendor/openlineage/1.55.0/OpenLineage.json), and the [version facet](../vendor/openlineage/1.55.0/DatasetVersionDatasetFacet.json).
- [Substrait](https://substrait.io/spec/specification/) for the plan format version selected by the qualified adapter.
- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) for DDK artifact version syntax.
- [YAML 1.2.2](https://yaml.org/spec/1.2.2/): optional YAML syntax, restricted by Section 4.

### 20.2 Informative references

[Research and references](references.md) records specific upstream versions, licenses, documented capabilities, and links for Data Contract CLI, Frictionless, dlt, Substrait, DataFusion, pytest, CUE, and W3C specification guidance. The adapter profiles record which behaviors remain proposed or unverified.
