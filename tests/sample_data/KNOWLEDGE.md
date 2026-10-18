# tests/sample_data/

Use these sample project archives for future application import and lineage testing.

## Files

- `dataforge_sql_lineage_test_project.zip` — SQL sample project ZIP.
- `dataforge_sas_lineage_test_project.zip` — SAS sample project ZIP.

## Expected structure (user-provided)

Each project contains 85 tables, 128 lineage edges and seven ETL layers:

| Layer | Tables | Role |
| --- | ---: | --- |
| 01 Sources | 16 | Source tables |
| 02 Extractions | 16 | Extracted tables |
| 03 Staging | 16 | Cleaned tables |
| 04 Core | 15 | Multi-source transformations |
| 05 Data Marts | 12 | Analytical marts |
| 06 Reports | 6 | Reporting tables |
| 07 Published | 4 | Final output tables |

Each archive also includes a `README.md`, script execution order, expected lineage
CSVs, a complete JSON lineage manifest and expected upstream/downstream query results.
The SAS project additionally contains 16 temporary WORK datasets to test
intermediate-table collapsing; these are additional to the 85 tables above.

## Recommended application test

1. Import either ZIP and select only its script extension: `.sql` for the SQL
   project or `.sas` for the SAS project.
2. Generate lineage and search for `pub.all_kpis`.
3. Confirm its upstream lineage spans all seven layers back to all 16 source tables.
4. For SAS, also verify intermediate-table collapsing with the 16 WORK datasets.

Use the bundled manifests, CSVs and query results as expected-output references.

## Reported verification and limits

The user reports both archives passed structural and lineage-manifest checks,
and the SQL transformations passed a SQLite compatibility execution check.
Full DuckDB execution and licensed SAS execution have not been verified.
These are fixture provenance notes, not results of a fresh application test.

## Parser9 acceptance (2026-10-18)

Fresh isolated scripts/verify_parity.py run preserves every original/SHA256,85persistent
tables and128logical edges per ZIP; pub.all_kpis reaches sevenlayers/all16sources.
SAS retains16WORK/144physical edges; both warm analyses reuse86caches. CLI/service/actual
MCP, dictionary and stored evidence checks pass without provider calls or imported execution.

## Application observations (2026-10-16)

Agent integration verification imported 86 scripts per ZIP using only its extension.
SQL matches all 128 logical edges; `pub.all_kpis` reaches all 16 sources across seven
layers. Its registry also contains seven isolated setup/schema names (92 total assets).
With parser version 8, SAS yields 101 assets (85 persistent and 16 WORK datasets),
144 physical / 128 collapsed logical edges, exactly matching the manifest.
`pub.all_kpis` reaches all 16 sources through all seven layers. Its 31 diagnostics
are eight macro warnings and 23 informational LIBNAME/inline-data notices; no parse
errors remain. Both warm refreshes reuse 86 caches. Older workspaces need analysis
to refresh parser caches, without reimporting source files.
Reproduce with `scripts/verify_agents.py`; no imported SQL/SAS is executed.
