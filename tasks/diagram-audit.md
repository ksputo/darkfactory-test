# Diagram Audit

Add a Diagram Audit sidebar to the Excalidraw browser application. Use a visible application control to open it and reuse existing Excalidraw UI components.

## Issues to detect

- Unbound arrow: an arrow has neither a start nor an end binding. One bound end is enough to exclude it from this rule.
- Empty frame: a frame has no non-deleted member elements. Use frame membership rather than visual overlap alone.
- Unsafe link: an element's link fails Excalidraw's existing URL-safety rules. Reuse those rules.

Ignore deleted elements. For the same scene, return the same results ordered by issue class and element ID. Audit computation must not change scene data.

## User behavior

- Show the total issue count and counts by issue class.
- Show accessible rows identifying the issue and affected element.
- Activating a row selects its element and brings it into view through the existing canvas mechanism.
- Keep keyboard interaction and accessible roles intact.
- Update results when the scene changes.
- Show an explicit clean-state message when there are no issues.
- Support the existing light and dark themes and localization conventions.

An existing sidebar tab can satisfy the visible-control requirement. Do not require a new button merely to match a test's assumption.

## Tests and scope

Add meaningful unit and interaction tests in `packages/excalidraw/tests/diagramAudit.test.tsx`. Test detection, stable ordering, deletion handling, non-mutation, row activation, updates, and the clean state. Use valid fixtures whose properties are asserted before testing the audit. Do not add filtering yet, change dependencies or configuration, weaken existing tests, or push changes upstream.
