# Inspect original source evidence

1. Select a relationship in the Lineage graph, or inspect a dependency in Tree view.
2. Expand its source file in the evidence area.
3. Check the statement, original line range, version and extraction method.
4. Compare the complete original source; a short excerpt may omit relevant context.

![Original safe SQL source with line numbers in the evidence viewer](../assets/images/gravetrail-source-evidence.png)

*Pending reimports do not rewrite the original analyzed version.*

Direction and selected nodes/relationships determine which files appear. Upstream and
downstream views can show different evidence sets. Collapsed temporary steps retain
their intermediate evidence chain.

For dbt artifacts, inspect **evidence origin** and **JSON Pointer**. Decoded compiled
SQL differs from original template text and raw JSON slices. Artifact-only imports
cannot show original repository files that were not supplied.

AI source-integrity checks do not prove semantic interpretation; those facts stay
inferred. Read [evidence limits](../concepts/evidence-and-coverage.md).

Source exports can contain private code. Review before sharing. CLI/MCP evidence
retrieval also requires source permission: [CLI](../CLI_GUIDE.md), [MCP](../MCP_INTEGRATION.md).
