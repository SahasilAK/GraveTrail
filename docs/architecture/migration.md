# Migration architecture

The Migration page uses the existing workspace Store, job journal, provider connections and
request budgeting. The migration service has no warehouse client or dbt runtime dependency.

`dataforge.migration.engine` plans outputs and source obligations before writing candidates.
Source-specific rules live in `sources.py`. SQLGlot parses and generates SQL with explicit dialects.
The emitter replaces recognized AST table references with literal dbt references. Independent
inspection uses inert table tokens and checks dependencies, output accounting, schema provenance,
cycles and generated graph edges. Unsupported semantics stay review findings. Unsupported or
unavailable sources stay visible in the inventory and coverage. A small registry and warehouse
adapter own the compatibility profile, dialect, materializations and type mapping.

Schema version 11 adds four workspace-owned tables. Project rows point at immutable revisions.
Source rows retain compressed decoded evidence and the snapshot retains original byte hashes,
encoding and admission metadata. Revision rows hold the plan, candidate files, schema decisions
and review bindings. Activity rows hold bounded request attempts, scoped responses, job references
and approved lesson versions. Workspace cleanup removes the migration rows. Source cleanup leaves
migration evidence intact, and the existing database backup includes all four tables.

Publication checks the expected revision inside one DuckDB transaction. Provider calls take place
outside transactions. Each explicitly dispatched physical attempt reserves capacity before sending.
An unknown outcome keeps its reservation across restarts. The current release uses one attempt per
explicit dispatch and allows retry of a prepared request within the cumulative project budget.
No response can publish code directly.

Static conversion checkpoints completed model lowering in bounded batches. Retrying the same
revision rebuilds inventory from the pinned snapshot and reuses completed model SQL and bindings
from the same converter version. Successful publication removes the temporary checkpoint records.

The registered handoff profile uses stable package releases
[dbt Core 1.10.13](https://pypi.org/project/dbt-core/1.10.13/) and
[dbt-databricks 1.10.13](https://pypi.org/project/dbt-databricks/1.10.13/).
This pins project generation and the external installation target. It carries no runtime
equivalence evidence.
