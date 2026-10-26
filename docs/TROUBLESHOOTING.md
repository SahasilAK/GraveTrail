# Troubleshooting

- **Directory rejected:** configure `DATAFORGE_ALLOWED_ROOTS` before startup. Resolved paths
  must remain inside one of those roots. Windows roots use `;`, Unix roots use `:`.
- **Import skipped a file:** inspect import diagnostics. Check chosen extensions, paths,
  encoding, binary content, file size and ZIP ratio. Rename unsafe archive members at their source.
- **No edges:** analysis may have only source/target assets, SELECT-only reads, unsupported
  constructs or unresolved macros. Read Analysis → Diagnostics and inspect source. Never assume
  a filename similar to a table creates a relationship.
- **Partial parse:** choose the correct SQL dialect/folder mapping and review unsupported
  SAS constructs. The rest of the workspace still works. Rebuild after parser/config changes.
- **Old source shown:** facts pin the analyzed hash. A new import is pending; analyze it to
  refresh lineage. Downloads shown with old evidence use the corresponding original bytes.
- **Provider unavailable:** verify its base URL, manual model/deployment, environment variable
  availability and privacy gates. Restart after setting keys. Azure listing is manual. A
  connection test uses no source files. HTTP errors are sanitized; inspect your provider separately.
- **Focused AI assistance quarantined:** schema, quote, known asset, range or read/write evidence checks failed.
  No inferred edges were added. Fix context, do not disable validation.
- **Database locked:** stop other Streamlit/Python processes using the same home. Use one
  app process per DuckDB home. Do not delete a database lock or database to bypass this.
- **Schema/graph changed after update:** restart Streamlit to refresh imported module/component
  definitions and migrations. Cached parses invalidate by parser version. Clear parser cache only
  if needed; that does not remove existing facts.
- **Large graph:** reduce depth/node limits or focus a closer asset. Use exported tables for
  comprehensive inspection. Cycles are safe but do not imply an executable schedule.
- **Recover after failure:** previous committed facts remain. Stop app, back up data home,
  correct the failing input/config and rerun. Restore a stopped-app backup for data recovery.


## Resumable AI analysis

Project builds use token-budgeted file parts and one active physical request per build.
There is no execution-window or files-per-request control. Preview must fit the full
request envelope within known model capacity and the authorized disclosure limits.
Check the selected model's capacity, output share and exact token overrides when packing
is blocked; a connection test alone does not establish capacity.

Resume compatible saved work to reuse successes. Source, settings, model or protocol
changes can invalidate a paused run; legacy protocols require a new build. Unknown
responses may have been processed or billed, so retry only under the configured unknown
policy or explicit acknowledgement. After bounded item recovery, available validated
lineage publishes with incomplete coverage; **Retry unresolved AI work** retries only
those items. Optional run ceilings retain cumulative attempts/output reservations across
recovery and resume; provider quotas/credits remain external limits.
For wait, cancellation, restart and retry actions, see
[AI controls and recovery](user-guide/ai-analysis-controls-and-recovery.md).

## dbt projects

Use the [dbt troubleshooting table](DBT_SUPPORT.md#troubleshooting) for project-root,
configured-path, supplied-package, artifact-schema and raw-source mismatch issues.
Source-only macro/Python column gaps are expected partial coverage. Reimport external
edits and rebuild before comparing results; inspect project mode, resource origin and
`analysis_current` rather than assuming a completed build has complete coverage.

## Missing assets after an interrupted process

A Windows/DuckDB 1.5.6 verification home showed empty indexed asset lookups after
interruption and WAL recovery, even though a full table scan found the saved rows.
An isolated forced-exit reproducer confirmed inconsistent secondary-index results;
normal graceful CLI close/reopen controls retained the expected SQL and dbt graphs.
This is an application/dependency issue, separate from the documentation build.

Do not interpret an unexpectedly empty search as proof that dependencies disappeared.
Stop processes using the home, preserve a copy including its WAL before further
recovery attempts, and report the version, interruption history and reproduction.
Do not delete the database or imported originals. The upstream
[DuckDB issue](https://github.com/duckdb/duckdb/issues/23788) tracks this class of
recovery problem; no fixed-version or repair guarantee is claimed here.
