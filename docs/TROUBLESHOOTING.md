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
- **AI quarantined:** schema, quote, known asset, range or read/write evidence checks failed.
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

A project estimate above 2,000 attempts is distinct from the per-execution ceiling. Auto continuation crosses windows within a finite project allowance. Context failures still require a fitting unit/model/disclosure allowance; provider quotas/credits remain external limits. For wait, restart, unknown-response and allowance actions, see [AI controls and recovery](user-guide/ai-analysis-controls-and-recovery.md).
