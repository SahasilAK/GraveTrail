# dbt project support

GraveTrail can inspect dbt projects offline. Import configured SQL models, property YAML,
macros, seeds, snapshots, Python models and test definitions as source evidence. Model
identity includes project root, package and version, so two projects can use the same name.
Imported SQL, Python, Jinja, hooks and dbt commands are never executed.

## Import and analyze

In **Sources**, choose **dbt project** as the project type. ZIP, browser-folder and allowed
host-directory imports use the same path and byte limits as ordinary source imports.
`dbt_project.yml` determines resource directories; custom paths are supported. Profiles,
dotfiles, logs and unselected generated outputs are excluded before their readers run.
Enable supplied package sources only when their code is included; GraveTrail downloads no packages.

Choose a mode:

- **source**: inspect literal `ref`/`source` dependencies, configs and parseable model queries.
- **enriched**: select an already-generated `manifest.json` using its exact import-relative
  path. A known raw-model/source mismatch rejects publication. Macro/variable compilation
  context remains explicitly unverifiable; artifact results describe that supplied snapshot.
- **artifact**: import a standalone manifest without its original project. Evidence links
  point to exact raw JSON resource slices; original repository files are unavailable.

Open **Analysis** and build lineage. Selecting a dbt member analyzes its project closure.
Any member change invalidates the project result, including changes to macros or YAML.
Committed normalized results survive parse-cache cleanup. Cancellation/failure preserves
the previous graph and resource catalog.

## Models, columns and resources

The normal Lineage, Columns and Transformations pages use logical dbt data assets. A model
SELECT writes its logical output without creating a synthetic source statement. SQL
projections feed the existing column engine; documented YAML columns alone do not imply
a complete physical schema or justify unused-column claims.

**dbt resources and macro impact** in Lineage lists models, sources, seeds, snapshots,
macros, tests and other declared resources. Inspect upstream dependencies or downstream
consumers. Macro calls, test attachments, exposures and semantic dependencies are typed
relationships, separate from the production model graph. Versions resolve using explicit
`v`/`version` or a declared latest version. Included package references can be qualified.
Resource pages expose the full inventory. Large impact tables show a bounded preview;
CLI/MCP continuation cursors provide the complete dependency traversal.

Source-only macro code is inventoried and linked to consumers, without expanding user
macros. Unknown control flow, dynamic refs and generated query fragments retain partial
coverage diagnostics. Python models provide literal dependency inventory, with no DataFrame
column-derivation claim. Snapshots describe dependencies rather than proving SCD execution.
Semantic resources are metadata/dependency inventory, not a MetricFlow compiler.
Legacy semantic YAML links simple metric measures and saved-query metrics. The newer
embedded semantic YAML v2 format is retained as model metadata; its nested metrics are
not separately resolved. See dbt's [semantic YAML migration guide](https://docs.getdbt.com/docs/build/latest-metrics-spec).

## Artifacts and evidence

The initial qualified manifest schema is **v12**. Compiled model SQL, when present, supplies
expression facts independently from declared DAG dependencies. Manifest DAG edges have
method `dbt-manifest`; these are artifact-declared dependencies rather than proof of a
warehouse read. Ephemeral logical nodes remain present in that DAG.

Original source text and generated SQL retain different origins. Artifact operations cite
real raw JSON slices, including escaping; decoded SQL is never represented as original JSON
text. The resource inspector displays evidence origin and JSON Pointer. Exact original
versions are retained while committed snapshots/history reference them.

Other artifact formats are admitted only when explicitly selected. Unsupported schemas,
missing compiled SQL and runtime-dependent expressions do not gain a completeness guarantee.
Qualified auxiliary readers are catalog **v1** and run-results **v6**; supplied run results
must match the manifest invocation. Freshness and semantic artifacts are retained as source
evidence only. Source SQL uses an explicit SQLGlot dialect; compiled fixture coverage
qualifies PostgreSQL syntax, not every adapter-specific construct.
The artifact metadata contract and schema numbering are documented by dbt:
[manifest](https://docs.getdbt.com/reference/artifacts/manifest-json),
[artifact metadata](https://docs.getdbt.com/reference/artifacts/dbt-artifacts).

## CLI, MCP and settings

```sh
gravetrail --home /path/to/home --allow-write --allowed-root /allowed/root ingest /allowed/root/project --workspace WORKSPACE_ID --source-kind dbt
gravetrail --home /path/to/home --allow-write lineage build --workspace WORKSPACE_ID
gravetrail --home /path/to/home dbt projects --workspace WORKSPACE_ID
gravetrail --home /path/to/home dbt resources --workspace WORKSPACE_ID --project-id PROJECT_ID
gravetrail --home /path/to/home dbt dependencies RESOURCE_ID --workspace WORKSPACE_ID --direction downstream
```

Use `--artifact-path target/manifest.json --dbt-mode artifact` for a standalone manifest
and `--include-packages` for already-supplied package code. Stop other owning processes of
the same DuckDB home before independent CLI access.

MCP adds `list_dbt_projects`, `list_dbt_resources`, `get_dbt_resource` and
`trace_dbt_dependencies`. Existing `ingest_sources` accepts `source_kind="dbt"` and
`dbt_options`. Normal workspace, write/import-root, source, paging and response-budget
permissions apply. Detailed resource evidence requires source access.

The validated **dbt** settings section supports mode, dialect, public variable values,
target label, selected artifact paths and per-root `projects` overrides. Only deliberately
non-secret variable values belong here. Never supply profiles, credentials or environment
values. Settings are included in portable workspace configuration and project freshness.

AI/hybrid project builds reject selected dbt sources before source disclosure. Use parser
analysis for dbt; ordinary SQL/SAS AI analysis remains available for separately selected files.

## Upgrade and recovery

Schema migration **8** adds workspace-scoped catalogs, relationships, evidence, relation
bindings and normalized project snapshots. Parser version **15** invalidates incompatible
parse caches. Existing SQL/SAS/CSV IDs and command defaults remain compatible. Back up a
stopped home before upgrading. Cleanup, integrity, backup/restore and guarded history
archives account for the new tables and referenced source blobs.

## Reproducible qualification

`uv run python scripts/benchmark_dbt.py --models 1000` builds a disposable chain/fanout
project with YAML and macro cases. On Windows / Python 3.11.16, with tracemalloc enabled:
cold analysis took **20.253 s**, cached analysis **14.792 s**, and a model edit **17.358 s**.
The runs analyzed/cached **1003/0**, **0/1003** and **1003/0** members respectively,
producing 1,000 model assets and 1,098 edges. Peak Python allocations were **57.68 MiB**;
this excludes DuckDB/native allocations and is not total process memory. Cached analysis
still materializes/validates the workspace. These are local observations, not thresholds.
