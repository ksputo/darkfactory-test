# Filter Audit

Extend the existing Diagram Audit browser interaction with a category filter. The default is All categories. Total counts always describe the whole scene, while stable rows show the selected category. Changing the filter must not mutate the scene or clear the current canvas selection. Keep the control accessible, support light and dark themes, and add focused tests without changing dependencies or configuration.

Offer All, unbound arrows, empty frames, and unsafe links. Preserve stable ordering within each filter, update results when the scene changes, and distinguish an empty filtered list from a scene with no issues. Extend `packages/excalidraw/tests/diagramAudit.test.tsx` with interaction tests for these behaviors. Commit the change locally.
