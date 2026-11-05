# Native binding and uncertain-operation examples

These are document-shape examples. Dataset names, paths, identities, and digest values are fictional. No native objects were created or resolved, and no operation was submitted.

- [bindings.ddk.json](bindings.ddk.json) illustrates the native alternative to a file binding. It is deliberately a partial binding example, not a runnable commerce design. The proposed reference scheme is unqualified.
- [unknown-operation.report.ddk.json](unknown-operation.report.ddk.json) illustrates an operational error with unknown managed execution and selection. Its required quality check has not run. The original operation ID remains available for reconciliation; the report does not prove that execution stopped or that no outputs exist.

Native references retain their own identity scheme and digest algorithm. They are not artifact SHA-256 hashes. Runtime validation and protection remain future integration work described in [runtime-integration.md](../../docs/runtime-integration.md).
