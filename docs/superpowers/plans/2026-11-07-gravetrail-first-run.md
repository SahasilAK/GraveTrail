# GraveTrail first run and coverage plan

## Scope

Apply the five feedback points on `feature/databricks-lineage`. Use the existing SQL archive at `tests/sample_data/dataforge_sql_lineage_test_project.zip` as the single source for the in-app demo, walkthrough, and recording. Retain the existing Ink dark palette and use it in the recording. Keep the current import, analysis, evidence, and lineage services.

## 1. Run the existing example in one click

- [x] Add a Streamlit AppTest that opens a fresh workspace, clicks **Run SQL example**, and checks the selected `pub.all_kpis` graph and source-backed dependencies. Confirm it fails before the button exists.
- [x] In `ui/pages/dashboard.py`, expose the button on the empty Overview. Explain that it imports the sample into the active empty workspace and runs local analysis. Guard against a second import after the workspace gains files. Use `Importer.zip` with `.sql`, `analyze`, `focus_asset`, and Streamlit navigation to open Lineage. Surface failures and keep imported files available for normal analysis if a build fails.
- [x] Use the existing wheel asset allowlist and Docker build context to ship exactly the existing SQL ZIP at the same application-relative path. Check the wheel contains the original bytes and use the existing build paths for packaged apps.
- [x] Put the one-click path first in `docs/getting-started/quick-start.md` and README. Keep the manual ZIP walkthrough and direct links to the existing SQL, SAS, and dbt archives for users who want to inspect or import them themselves.

## 2. Explain where GraveTrail fits

- [x] Add a compact **Why GraveTrail?** section to `docs/index.md` and a short version to the empty Overview. Describe GraveTrail's local static analysis of imported scripts and its evidence workspace. Use Databricks' documentation for Unity Catalog runtime lineage and SQLGlot's documentation for the embeddable parser it provides. State the static analysis boundary.

## 3. Explain confidence and coverage

- [x] Check the edge materialization and trace code. In `docs/TRANSFORMATION_LINEAGE.md`, explain the evidence confidence values and how the UI summarizes them. Explain trace completeness in terms of unresolved boundaries and traversal limits. Include an example of a known value path with an ambiguous sibling input.
- [x] Link to the explanation from the homepage and add a short explanation beside the app's coverage count. Keep the existing scoring, privacy, and coverage behavior.

## 4. Show the actual workflow

- [x] Launch GraveTrail with a temporary data home, select Ink dark, and record the button, the focused `pub.all_kpis` graph, and its source evidence. Keep the recording short and use the visible app workflow as captured.
- [x] Encode one compact silent MP4 and publish it through the existing named MkDocs asset allowlist. Give playback controls and a text description on the homepage. Verify the encoded clip and the built site's media path.

## 5. Show SAS and generated-code boundaries

- [x] In `docs/SAS_PARSING.md`, show a `%LET`-resolved table read and a runtime-generated case that stays unresolved. Distinguish table-level recognition from column-level evidence. Cross-link the existing SQL documentation for supported literal dynamic SQL and its runtime limits.
- [x] Link to the SAS examples from the homepage. Use parser fixtures to check the expected behavior of each documented example.

## Verification

- [x] Run focused AppTest, packaging, and parser tests, then the full pytest suite and Ruff.
- [x] Build and validate the public documentation, including links, anchors, and the recording. Smoke-test the first-run path in a fresh browser session. Refresh the relevant tracked knowledge maps.

The example opens at upstream depth 30. Browser verification covered the full graph, original SQL evidence, and playback at mobile width. The final suite reported 1,022 passed and 2 skipped. Ruff, the lock check, and the strict documentation build passed. Docker runtime verification was unavailable because the engine was stopped.
