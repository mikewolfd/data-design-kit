# Commerce product catalog example

[Product definition](product.odps.json) declares named inputs and an output using ODPS. The [project catalog configuration](../project.ddk.json) selects the relevant objects because those ports reference the same [ODCS contract](../datasets/commerce.odcs.json). It also declares the customer relationship and references the maintained revenue SQL as a query example.

[Illustrative metadata](metadata.example.json) represents the records a native adapter would read. It supplies one source occurrence, exact data versions, an example run, a release, and a publisher selection. The [catalog view](catalog.ddk.json) retains their references, the original input digests, and an unresolved saved-plan fixture result. Its example service locations use reserved domains.

[DCAT discovery](discovery.dcat.json) links the revenue dataset to the selected version and distribution. The OpenLineage [job definition](job.openlineage.json), [start](start.openlineage.json), and [completion](complete.openlineage.json) separate the declared `summarize` component job from its illustrative observed run. The version facet values resolve to the catalog versions. The run ID resolves to the native reference in the catalog.

The catalog uses the authoring project as the origin for its relative SQL path. Companion file paths in `files` resolve relative to the catalog. The example metadata uses an illustrative publisher namespace. The `urn:example:commerce:definition:*` source inventory entries refer to the project, product, contract, and revenue SQL linked above.

The receipt, release, and events are authored examples. The [independent SQL fixture](../tests/revenue.fixture.ddk.json) supplies expected results for future SQL and saved Substrait tests. Document validation establishes the consistency of these shapes and references. Runtime conformance remains planned.
