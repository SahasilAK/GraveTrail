# dbt/

`analysis.parse_model_query` uses shared SQL reachable scopes, excluding unused CTE
column facts while preserving reachable intermediate steps and model identities.

Offline, bounded dbt project inspection; never evaluates Jinja/Python, runs dbt or opens profiles.

- `imports.py` — DbtImportOptions/preview_dbt_import; configured path admission and exclusions before reads.
- `yaml.py` — safe YAML conversion, duplicate/tag/cycle/depth budgets and path validation.
- `models.py` — immutable source/evidence/resource/project contracts and portable DbtSettings.
- `discovery.py` — root/package membership, artifact selection and project fingerprints.
- `templates.py` — static Jinja blocks/calls; conditional/nested refs stay candidates.
- `resources.py` — SQL/Python/YAML/seed/macro inventory, versions, static config and source tests.
- `resolution.py` — package/version reference resolution; logical identity and physical bindings.
- `artifacts.py` — bounded JSON with exact spans; manifest v12/catalog v1/run-results v6.
- `analysis.py` — project DAG and model query facts through SQLGlot; conservative runtime gaps.
- `evidence.py` — original offsets and JSON Pointer validation across retained versions.
- `persistence.py` — migration8 schema, normalized snapshots and staged catalog/evidence rows.
- `service.py` — project closure/cache/AI exclusion and shared DbtOperations reports.
- `__init__.py` — package marker.

services.py publishes catalog/snapshots and ordinary graph/column facts atomically.
CLI/MCP/UI reuse these readers; generated SQL has separate compiled_sql evidence.
