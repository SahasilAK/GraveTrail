# User guide

![GraveTrail lineage explorer showing the supplied SQL project at depth 30](../assets/images/lineage-explorer.png)

*Actual local application, captured with the included SQL project in an isolated home.*

Start with a focused question: which sources feed this table, which reports depend on
it, or where is this column used? GraveTrail connects the answer to original source
evidence and keeps unresolved cases visible. The [detailed user reference](../USER_GUIDE.md)
documents individual controls and settings.

## Build a trustworthy workspace

??? example "View the sample workspace dashboard"
    ![Actual dashboard: 86 SQL files, 92 registered assets, 128 dependencies and no diagnostics](../assets/images/workspace-dashboard.png)

Create or select a workspace in the sidebar. Workspaces retain their own inventory,
analysis, settings and provider profiles. In **Lineage builder**, import a ZIP,
browser folder or explicitly allowed host directory, selecting only the relevant
extensions. Inspect accepted/skipped files and diagnostics before analyzing.

Imports are additive: omitting a file from a later import does not delete it. Reimporting
the same path replaces the active inventory entry while retaining originals referenced
by earlier evidence. Normal analysis reuses compatible unchanged parses; **Rebuild**
forces parsing. A failed run preserves the previous committed graph.

Use the [quick start](../getting-started/quick-start.md) for a reproducible SQL or SAS
example. Consult [SQL parsing](../SQL_PARSING.md) and [SAS parsing](../SAS_PARSING.md)
when a language construct produces an unresolved diagnostic.

## Explore dependencies and evidence

Search in **Lineage explorer**, then select the exact asset. Identically named tables
in different schemas or temporary jobs are separate candidates. Upstream traces inputs;
downstream traces consumers. Choose graph direction, traversal depth and whether to
collapse temporary stages for the question you are answering.

Trees load branches progressively. Graph/tree limits and path boundaries can restrict
what is visible; a bounded view is not evidence that no more dependencies exist. Cycles
are reported and traversal terminates. Selecting a node or edge changes the source
evidence scope, while the upstream/downstream tabs control their own tree context.

Every relationship retains source version, statement, original line range and extraction
method. If new code is pending, an older relationship displays the original analyzed
version. Analyze the imported revision before expecting the graph to reflect it.
Collapsed temporary steps retain their intermediate evidence. Logical path steps do not
establish runtime execution order.

??? example "Inspect the complete original SQL"
    ![Original SQL source viewer showing the imported statement and exact line numbers](../assets/images/source-evidence.png)

## Inspect direct column usage

In **Column usage**, choose a source asset, filter columns and group by file
or usage context. Results describe direct references. Unqualified ambiguous columns
remain diagnostics. A plain wildcard can expand from consistent imported SQL CREATE
TABLE declarations as inferred references, with declaration provenance; otherwise
coverage remains unknown. No live database lookup or CSV/table-name guess fills gaps.

## Use diagnostics and optional assistance

Review warnings/errors in Builder before accepting a graph as complete. The unresolved
review queue offers bounded statement context and original line selection. Previewing
is local. A separate explicit AI request uses configured task routing, privacy gates,
credentials and context budgets. Changed source must be previewed again.

Validated relationships can be merged as inferred evidence. Quarantined or advisory
results cannot silently become graph facts, and a merge does not erase unrelated parser
warnings. Continue with [LLM integration](../LLM_INTEGRATION.md) and
[secure configuration](../SECURE_CONFIGURATION.md) if assistance is useful.

## Choose the right output

| Need | Output or tool |
| --- | --- |
| Review or share relationships | Lineage CSV/JSON or offline HTML graph |
| Follow ordered logical dependencies | Dependency paths CSV/JSON with source evidence and boundaries |
| Inspect the code behind selected assets | Relevant original source ZIP or byte-exact file download |
| Find literal code or assess a change | Code search, dictionary and static impact tools |
| Compare analyses | Completed-run comparison |
| Query an analyzed project from automation | [CLI](../CLI_GUIDE.md) or [MCP](../MCP_INTEGRATION.md) |

Exports can disclose complete private code and retained evidence. Review them before
sharing. CSV formula-leading values are escaped, but that does not remove confidential
source content.

## Maintain the workspace

Configuration transfers move selected preferences into a new workspace; they are not
backups. General cleanup uses preview/apply guards and mandatory backups. Source or AI
removal invalidates the whole dependent graph; shared cache and original blobs are
separate cleanup scopes. Retained history may protect originals from orphan collection.
Logical deletion does not guarantee a smaller DuckDB file.

Read [data management and cleanup](../DATA_MANAGEMENT.md) for category effects,
backup/restore and recovery limits. For startup/storage issues use
[configuration](../getting-started/configuration.md) or [troubleshooting](../troubleshooting/help.md).
