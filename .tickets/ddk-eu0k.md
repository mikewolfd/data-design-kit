---
id: ddk-eu0k
status: open
deps: []
links: [ddk-arnm, ddk-zxlb]
created: 2026-11-13T19:44:54Z
type: bug
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Open admitted data without a full-file digest pass on every cold reader

Owner role: DocSpec reader owner, with the DDK viewer adapter owner.

User outcome: Large tables open predictably and read only the data needed for the requested page or query.

F3: use authoritative immutable native versions for already-admitted data and an explicit admission path for external files. Reuse maintained readers and storage identity. A larger digest cap alone does not solve repeated whole-file work. Coordinate selected-page decoding with the existing dr-agq0 task; measure hashing and decoding separately.

Sources: [F3](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#f3--concern-cold-reads-still-perform-full-file-work), [selected-page task](/Users/mikewolfd/Work/spicy-stack/docspec-rs/.tickets/dr-agq0.md).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Bind a real workload and numerical cold/warm latency, bytes-read, request, memory and disk targets from the workload ticket before measuring.
- Exercise a file larger than the current default 256 MiB verification cap, many shards, and a large single-row-group file; retain cold and warm measurements and exact identities.
- Already-admitted immutable versions open without repeating whole-file verification; external admission, changed-file and wrong-version refusals remain effective.
- A one-page read does not verify every unrelated shard or decode every preceding row; prove actual I/O rather than returned-row counts.
- Verify cancellation and concurrency limits through the actual configured viewer/query consumer.
