# AI Mapper Studio browser retest changes — 2026-11-16

This report lists changes for the supported-browser retest. Other uncommitted
Mapper/Transformer work already present in the workspace is outside this list.

| File | Change |
| --- | --- |
| `backend/app/mapper_assistant.py` | Generate explicit `${last.…}` source references; recognize existing wrapped loop sources when reusing authored loops. |
| `backend/app/main.py` | Preserve `input`/`last` aliases in visual Mapper tests so mixed old/new nested selectors share the correct scope. |
| `backend/tests/test_mapper_assistant.py` | Regression for previewing a reused authored outer loop with new wrapped nested sources. |
| `frontend/src/mapperSchemaSample.ts` | Bounded JSON sample/compact definition normalization for nested schema fields. |
| `frontend/src/ActivityEditor.tsx` | Use normalized sample schemas and selected source paths for Input validation and completion, including nested bindings. |
| `frontend/src/MapperStudio.tsx` | Invalidate changed preview results, clear cached output and cancel/ignore stale requests; stable empty collection defaults. |
| `frontend/scripts/mapper-assistant.test.mjs` | Nested sample inference, explicit schema preservation, prototype safety and depth-limit regressions. |
| `scripts/mapper-studio-saved-qa.py` | Execute actual browser-saved rules through complete Run/Debug and both generated Python archive flows. |
| `docs/MAPPER_ASSISTED_MAPPING.md` | Explain browser verification, source syntax, sample inference and preview invalidation. |
| `docs/validation/mapper-studio-ui-summary-2026-11-16.json` | Consolidated validation outcomes and limits. |
| `docs/validation/mapper-studio-ui-2026-11-16/` | Browser checks, saved-project execution results and screenshots. |
| `frontend/scripts/developer-documentation.mjs` | Include the new helper and saved-project QA script in Studio developer help. |
| `frontend/public/help/MINA-Developer-Guide.pdf`, `MINA-Documentation.pdf`, `developer-data.json`, `documentation-build.json`, `documentation-data.js`, `documentation-data.json` | Regenerated Studio help from the updated sources. |
| `frontend/dist/index.html` | Updated production bundle entry from the verified Studio build. |

Temporary servers, isolated project data, generated verification archives and
test logs stay under ignored `tmp/`; they are not production dependencies.
