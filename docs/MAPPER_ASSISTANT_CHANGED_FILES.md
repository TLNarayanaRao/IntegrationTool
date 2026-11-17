# Assisted mapping — changed files

Changes for this request; earlier Mapper/Transformer workspace changes are
preserved separately. No new third-party dependency or external AI service is added.

| File | Change |
| --- | --- |
| [mapper_assistant.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapper_assistant.py) | New bounded, indexed mapping planner; semantic vocabulary, explicit choices, reasons, type/cardinality checks, nested loops, safe reuse of authored For-Each loops, scalar-array copies and branch protection |
| [main.py](/D:/Integration-tool/IntegrationFabric/backend/app/main.py) | New `/api/mapper/plan` endpoint using resolved schema documents and reviewed learning |
| [mapper_binding.py](/D:/Integration-tool/IntegrationFabric/backend/app/mapper_binding.py) | Generate/reopen scalar repeating Copy-Of bindings in XSLT |
| [MapperStudio.tsx](/D:/Integration-tool/IntegrationFabric/frontend/src/MapperStudio.tsx) | Review/apply/undo workflow; stale-request cancellation, predecessor inference, vocabulary options, field search, unmapped view, shared target suggestions and bounded initial rendering |
| [MappingPlanReview.tsx](/D:/Integration-tool/IntegrationFabric/frontend/src/MappingPlanReview.tsx) | New inline review with alternatives, explanations, required gaps and manual stylesheet guard |
| [mapper-assistant-ui.ts](/D:/Integration-tool/IntegrationFabric/frontend/src/mapper-assistant-ui.ts) | Recover a source schema from upstream contract metadata while preserving cardinalities |
| [mapper-studio.css](/D:/Integration-tool/IntegrationFabric/frontend/src/mapper-studio.css) | Scrollable review, warning and vocabulary controls inside the existing viewport-safe ModalLayer |
| [test_mapper_assistant.py](/D:/Integration-tool/IntegrationFabric/backend/tests/test_mapper_assistant.py) | New tests for planning, ambiguity, manual/branch protection, aliases, XSD/references, large schemas, scalar arrays, target validation and all four execution modes |
| [mapper-assistant.test.mjs](/D:/Integration-tool/IntegrationFabric/frontend/scripts/mapper-assistant.test.mjs) | Upstream metadata and review rendering tests, including bounded rows, escaping and manual stylesheet guard |
| [mapper-assistant-qa.py](/D:/Integration-tool/IntegrationFabric/scripts/mapper-assistant-qa.py) | Reproducible indexed-planning benchmark and complete-flow audit in Run/Debug/both archives |
| [Assisted mapping guide](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_ASSISTED_MAPPING.md) | Workflow, examples, limits, AI scope, performance evidence and testing guidance |
| [Validation summary](/D:/Integration-tool/IntegrationFabric/docs/validation/mapper-assistant-summary-2026-11-16.json) | Functional and benchmark results |
| [build-documentation.mjs](/D:/Integration-tool/IntegrationFabric/frontend/scripts/build-documentation.mjs) | Include the new guide in Studio Help |
| [developer-documentation.mjs](/D:/Integration-tool/IntegrationFabric/frontend/scripts/developer-documentation.mjs) | Include implementation, editor components, tests and QA script in source navigation |
| [documentation-data.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.json) | Regenerated Studio Help |
| [documentation-data.js](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-data.js) | Regenerated offline Help |
| [developer-data.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/developer-data.json) | Regenerated developer Help |
| [documentation-build.json](/D:/Integration-tool/IntegrationFabric/frontend/public/help/documentation-build.json) | Updated coverage and fingerprints |
| [MINA-Documentation.pdf](/D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Documentation.pdf) | Regenerated user guide |
| [MINA-Developer-Guide.pdf](/D:/Integration-tool/IntegrationFabric/frontend/public/help/MINA-Developer-Guide.pdf) | Regenerated developer guide |
| [dist/index.html](/D:/Integration-tool/IntegrationFabric/frontend/dist/index.html) | Studio production build entry point; regenerate assets in another checkout |
| [This report](/D:/Integration-tool/IntegrationFabric/docs/MAPPER_ASSISTANT_CHANGED_FILES.md) | Request-specific file inventory |

Plans compile to ordinary Mapper rules. Runtime exports do not require the design
assistant to be installed separately. AI assistance here means local schema and
vocabulary matching plus explicitly shared field preferences, not a remote LLM.
Verification results, including the scope of the timing measurement, are recorded
in the linked validation report.

## Verification

- Backend suite: **712 tests, 11 skipped, no failures**. Final focused Mapper regression: **34 tests passed**, including later loop-reuse and API-option checks.
- Editor metadata/rendering and Studio Help: **21 tests passed**. TypeScript, production build and documentation fingerprints passed.
- Preview and target-schema-validated Run, Debug, direct Python and engine Python archives passed for nested loops, scalar copies, empty collections and filling missing children while retaining authored values.
- Indexed planning for 2,000 synthetic fields: **0.070459 seconds**, 2,000 candidate comparisons. All 2,000 values were audited in a complete flow in all four modes. This is not a UI latency or soak measurement.
- The production build retains its existing large-chunk advisory; it succeeds.
