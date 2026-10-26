# dbt project support

This reference describes the source checkout at **`1864dc8`** on
`codex/resumable-ai-lineage`. The published **v0.0.1** release predates dbt support;
use the [source installation](SETUP_AND_DEPLOYMENT.md#4-python-installation) for these features.
Start with [Analyze a dbt project](project-types/dbt.md) for the workflow or the
[dbt retail example](examples/dbt.md) for reproducible input and expected results.

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

### Project roots and admitted files

Each `dbt_project.yml` establishes a root and literal package name. Independent roots
retain separate model and column identities even when names match. Included installed
packages stay in their parent project's context and retain their own package names.
Artifact selection and per-root overrides use **import-relative** paths, including any
enclosing ZIP folder.

| Setting | Default | Admitted evidence |
| --- | --- | --- |
| `model-paths` | `[models]` | SQL/Python models, property YAML, Markdown |
| `macro-paths` | `[macros]` | SQL macro/custom blocks and property YAML |
| `seed-paths` | `[seeds]` | CSV seeds and property YAML |
| `snapshot-paths` | `[snapshots]` | SQL snapshot blocks and YAML declarations |
| `test-paths` | `[tests]` | SQL tests, YAML declarations and CSV fixtures |
| `analysis-paths` | `[analyses]` | SQL analysis inventory |
| `docs-paths` | `[docs]` | Markdown docs blocks |

Paths must be literal relative paths. Absolute paths, `..`, backslashes and Jinja paths
are rejected. Case-colliding paths, duplicate YAML keys, unsafe tags, cyclic aliases and
over-budget structures are rejected. `packages.yml`, `packages.yaml`, `package-lock.yml`,
`dependencies.yml` and `selectors.yml` are admitted as configuration evidence; declarations
alone do not install missing package code. `packages-install-path` defaults to
`dbt_packages`, and `target-path` to `target`.

Generated target outputs are excluded unless explicitly selected. Recognized artifact
names are `manifest.json`, `catalog.json`, `run_results.json`, `sources.json`,
`freshness.json`, `semantic_manifest.json` and `osi_document.json`. Selected files under
`compiled/` require a project context, but selection alone does not bind or analyze those
files: compiled model analysis reads `compiled_code` from the selected manifest.

### Source, enriched and artifact modes

Choose a dbt evidence mode independently from the parser/AI analysis choice:

- **source**: inspect literal `ref`/`source` dependencies, configs and parseable model queries.
- **enriched**: select an already-generated `manifest.json` using its exact import-relative
  path. A known raw-model/source mismatch rejects publication. Macro/variable compilation
  context remains explicitly unverifiable; artifact results describe that supplied snapshot.
- **artifact**: import a standalone manifest without its original project. Evidence links
  point to exact raw JSON resource slices; original repository files are unavailable.

The enriched `raw_code` check covers original model files that are present; it cannot
certify missing files, macro versions, variables, target context or warehouse execution.
Without a selected/present manifest, enriched mode falls back to source analysis. Inspect
project coverage to confirm which evidence actually produced a result.
Manifest-derived coverage reports `mode: artifact` even when the requested input mode was
enriched; `artifact_declared`, `schema: manifest/v12` and `context_status: unverifiable`
describe the actual evidence boundary.

Open **Analysis** and build lineage. Selecting a dbt member analyzes its project closure.
Any member change invalidates the project result, including changes to macros or YAML.
Committed normalized results survive parse-cache cleanup. Cancellation/failure preserves
the previous graph and resource catalog.
Reimport external edits before rebuilding: editing the original folder alone does not
change the stored snapshot. Changes to dbt settings also make analysis stale.

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

| Resource/evidence | Static behavior and boundary |
| --- | --- |
| Models/sources | Literal `ref('name')`, `ref('package', 'name')`, `source('name', 'table')`; disabled targets do not resolve. Root/package/version identify logical outputs. |
| Versions | YAML `versions`, optional `defined_in` and `latest_version`; explicit `v=`/`version=` selects a version. Missing/ambiguous targets remain unresolved. |
| Configuration | Literal project folder/model `+` config, YAML config and SQL `config()`; inline SQL config takes precedence. Database/schema/alias bindings remain partial source observations; profiles and naming macros are not evaluated. |
| Macros | Macro, generic test and materialization blocks are inventoried; resolvable calls produce `macro_call` links. Impact follows consumers, including nested macro calls. Bodies are never expanded into model SQL. |
| Seeds | CSV header metadata and file-to-logical-seed lineage. Header names do not establish warehouse types. |
| Snapshots | SQL blocks and YAML `relation` dependencies; no SCD execution or generated snapshot-column guarantee. |
| Tests | Singular SQL tests, YAML model/column/source tests and unit-test definitions; `test_of` attachments stay outside the production graph. Tests are never run. |
| Exposures/semantic resources | `exposure_of` and simple `semantic_dependency` inventory; no dashboard access or metric evaluation. |
| Docs/groups/selectors/package declarations | Supplied metadata inventory; these are not production data assets. |

Only **resolved** relationships enter dependency traversal. Candidate references do not
become proven reads. A `depends_on:` comment produces an ordering declaration
(`declared_dependency`), separate from data reads. The resource graph and normal data graph
answer different questions: a macro consumer or test attachment need not be a table edge.

Source-only macro code is inventoried and linked to consumers, without expanding user
macros. Unknown control flow, dynamic refs and generated query fragments retain partial
coverage diagnostics. Python models provide literal dependency inventory, with no DataFrame
column-derivation claim. Snapshots describe dependencies rather than proving SCD execution.
Semantic resources are metadata/dependency inventory, not a MetricFlow compiler.
Legacy semantic YAML links simple metric measures and saved-query metrics. The newer
embedded semantic YAML v2 format is retained as model metadata; its nested metrics are
not separately resolved. See dbt's [semantic YAML migration guide](https://docs.getdbt.com/docs/build/latest-metrics-spec).

`var()` can supply literal reference arguments from project `vars`, configured
`public_vars` or literal defaults. This is static substitution. `env_var`, `target`, `this`,
`is_incremental`, `run_query`, adapter dispatch, generated query fragments, loops and
conditional/nested references cannot establish complete source-only columns. Known
dependencies can still survive partial expressions. Python AST inspection records literal
`dbt.ref`/`dbt.source` calls; conditional or shadowed calls do not prove reads.

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

| Supplied format | Qualified behavior |
| --- | --- |
| `manifest/v12` | Declared resources, node/macro dependencies and available SQL-model `compiled_code`. The exact schema URL is required. |
| `catalog/v1` | Observed columns, generation time and catalog error presence. Resource IDs and database/schema/relation tuples must match the manifest; supplied project names must agree. |
| `run-results/v6` | Observed status, execution time and failures. Resource IDs must belong to the manifest and `invocation_id` must match exactly. |
| Freshness/semantic/OSI and selected compiled files | Retained evidence only; no separate semantic, freshness or compiled-file lineage reader. |
| Other schema versions | Rejected by qualified readers. Renaming files or changing a schema URL does not qualify incompatible payloads. |

Schema numbers identify JSON contracts rather than every release of dbt Core. The
manifest retains ephemeral logical hops; compiled SQL does not flatten them into invented
direct DAG edges. Independently parsed compiled SQL can still expose external physical
reads absent from the declared DAG.

Evidence origins distinguish `source_static`, `artifact_declared`, `compiled_sql` and
`ai_inferred`. A successful evidence integrity check proves retained ranges/pointers match
content; it does not prove runtime behavior or semantic completeness.

## CLI, MCP and settings

```sh
gravetrail --home /path/to/home --json --allow-write workspace create "dbt review"
gravetrail --home /path/to/home --allow-write --allowed-root /allowed/root ingest /allowed/root/project --workspace WORKSPACE_ID --source-kind dbt
gravetrail --home /path/to/home --allow-write lineage build --workspace WORKSPACE_ID
gravetrail --home /path/to/home dbt projects --workspace WORKSPACE_ID
gravetrail --home /path/to/home dbt resources --workspace WORKSPACE_ID --project-id PROJECT_ID
gravetrail --home /path/to/home --detail detailed dbt resource RESOURCE_ID --workspace WORKSPACE_ID
gravetrail --home /path/to/home dbt dependencies RESOURCE_ID --workspace WORKSPACE_ID --direction downstream
```

Use `--artifact-path target/manifest.json --dbt-mode artifact` for a standalone manifest
and `--include-packages` for already-supplied package code. Stop other owning processes of
the same DuckDB home before independent CLI access.

MCP adds `list_dbt_projects`, `list_dbt_resources`, `get_dbt_resource` and
`trace_dbt_dependencies`. Existing `ingest_sources` accepts `source_kind="dbt"` and
`dbt_options`. Normal workspace, write/import-root, source, paging and response-budget
permissions apply. Detailed resource evidence requires source access.
Filter inventory with `--resource-type macro` and dependencies with `--kind macro_call`.
Dependency depth is 1–30 (default 10); `depth_boundary` reports a depth boundary. Global
`--limit`, `--cursor` and `--max-chars` precede subcommands. Follow `next_cursor` and inspect
`complete`; UI impact previews are bounded. MCP uses `options` for paging/detail controls.
Use inventory's `asset_id` for graph queries with duplicate/versioned names.

The validated **dbt** settings section supports mode, dialect, public variable values,
target label, selected artifact paths and per-root `projects` overrides. Only deliberately
non-secret variable values belong here. Never supply profiles, credentials or environment
values. Settings are included in portable workspace configuration and project freshness.

Project **AI** builds include dbt alongside SQL and SAS. Project membership selects
resource/package/version identity, YAML, relevant nested macros and supplied artifact
origin. Selecting a member includes the disclosed project closure, including context-only
files. Preview that disclosure before dispatch. AI extraction uses source context and safe
resource inventory independently of static parser lineage answers. It publishes validated
AI data-flow facts without filling omissions from parser results. An explicit parser build
remains available separately. **Hybrid comparison and additional AI review are rejected
in this checkout.**
Dynamic Jinja, Python column semantics and unsupported compiled-to-original mappings
remain partial. Manual range assistance still requires project-aware context; use
project AI analysis instead. AI is optional and requires a configured provider,
source/write access and explicit network authorization for CLI/MCP. See
[the AI flow](user-guide/ai-analysis-flow.md).

### Troubleshooting

| Symptom | Check or next action |
| --- | --- |
| No dbt project found | Include `dbt_project.yml`, choose **dbt project** and retain directory structure. Explicitly select the manifest for standalone artifact mode. |
| Missing resources | Check resource paths, disabled config, supplied packages and import diagnostics. Files outside configured paths are not automatically models. |
| Missing package ref | Supply installed code and enable package sources; a package declaration alone is insufficient. |
| Source mismatch | Import a manifest compiled outside GraveTrail from matching sources, or select source mode. The previous graph is retained. |
| Unsupported artifact/context | Use qualified schemas, one manifest per context, matching run invocation and matching catalog physical relations. |
| Enriched result has source coverage | Check the exact import-relative manifest path; retention and selection are separate. |
| Missing macro-derived columns | Inspect partial diagnostics; consider a matching compiled manifest or optional project AI facts with evidence. |
| Ambiguous `orders` | Resolve asset/resource IDs, version and root in inventory. |
| Evidence absent/forbidden | Summary omits source. Request detailed output and check workspace source permission. |
| DuckDB cannot open | Stop the UI/MCP/other owner of that home, or use a separate disposable home. |
| Result still shows old files | Reimport and rebuild; check `analysis_current` and settings freshness. |

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
