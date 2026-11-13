---
id: ddk-p6kl
status: open
deps: []
links: [ddk-arnm, ddk-zxlb]
created: 2026-11-13T19:44:54Z
type: task
priority: 1
tags: [ddk, greenfield, lessons-review]
---
# Connect maintained source readers to resumable acquisition and DocSpec jobs

Owner role: SpicyDocs/source-library owners with DocSpec job integration; DDK consumes source/run metadata.

User outcome: Fresh products acquire and refresh selected sources with little application infrastructure code.

F5: compose existing source readers, retained acquisition records, declared inputs and native jobs. Source libraries own publisher pagination/parsing; products select scope and domain interpretation. Use an existing scheduler and native recovery. Reuse retained originals by exact identity and admit resource use before effects.

Sources: [F5](/Users/mikewolfd/Work/artifacts/ddk-lessons-review-2026-11-13/REVIEW.md#f5--blocker-to-readiness-source-acquisition-and-refresh-have-not-been-demonstrated-as-a-complete-shared-workflow), [source modes](/Users/mikewolfd/Work/spicy-stack/spicy-docs/docs/source-workflows.md).

Greenfield scope, priorities and evidence: [work backlog](/Users/mikewolfd/Work/data-design-kit/docs/work-backlog.md#greenfield-delivery).

## Acceptance Criteria

- Choose one real question/source family with the fresh application and complete acquisition through native input binding; expand across every materially different selected mode.
- Cover immutable bulk files, mutable paged APIs, dated/versioned documents and selected PDF/XML extraction where the required inventory includes them.
- Distinguish successful empty, incomplete crawl, unavailable period, explicit deletion and failed refresh; preserve original attempt and source-version identities on recovery.
- Check publisher meaning/units against bounded visual review of retained originals when adding a source, retaining source hash/locator, findings and limits.
- Measure unchanged refreshes, small corrections/deletions and interruption/resume; keep completed capture/check work reusable and implement no new scheduler or recovery database.
