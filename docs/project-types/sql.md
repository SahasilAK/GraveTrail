# Analyze a SQL project

In **Sources**, select SQL for a file, ZIP or folder import. Choose **SQL source
type** to select Databricks, SQL Server, another supported dialect, or **Generic SQL**.
Choose **Use workspace settings** to inherit the workspace dialect rules. Select
**Continue to Analysis**, then run **Analyze all files** with AI unchecked.

Use **Lineage** for table dependencies and **Columns → Lineage graph** to trace
output expressions. Switch to **Direct references** to find usage in the original
code. The selected SQL source type applies to table and column analysis. A known
schema can resolve wildcard expansion and positional INSERT mappings. Check
diagnostics for missing schemas, ambiguous references and dynamic names.

Some literal procedure/dynamic-SQL wrappers are supported, but arbitrary runtime
generation remains unresolved. See [SQL coverage](../SQL_PARSING.md) and
[transformation coverage](../TRANSFORMATION_LINEAGE.md).

Try [the SQL tutorial](../examples/sql.md). Optional [AI](../AI_ANALYSIS.md) is a separate
inferred workflow, not a requirement for large projects.
