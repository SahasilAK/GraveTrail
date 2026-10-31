# Projects, workspaces and source versions

A **workspace** contains an inventory, settings, provider profiles and saved analysis.
Use one for a related system or investigation. Switching workspaces changes query
scope; it does not start analysis.

A **source** is an imported file with a path, content hash and retained original bytes.
Import is additive. Reimporting a path updates its active content; omitting it later
does not delete it. Older evidence can still reference the analyzed original version.

A **dbt project** adds a root, package/version identities and configured resource paths
within a workspace. Its members are analyzed together; a macro or YAML change can
invalidate the project even if model SQL has not changed.

An **analysis** reads inventory and publishes a graph revision. Compatible unchanged
static parses can be reused. Failed work preserves the previous graph, so pending
imports can be newer than what you are viewing. Check freshness.

The **data home** holds DuckDB, original blobs and runtime artifacts. It differs from
the workspace and the application checkout. One process owns it at a time: stop the
UI before opening the same home from an independent CLI or MCP process.

See [sources](../user-guide/sources.md), [configuration](../getting-started/configuration.md)
and [history and recovery](../DATA_MANAGEMENT.md).
