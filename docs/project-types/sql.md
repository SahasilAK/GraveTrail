# Analyze a SQL project

Import a ZIP/folder in **Sources**, choose ordinary files and select `sql`.
Run **Analysis → Run → Analyze all files** with AI unchecked.

Set the appropriate SQL dialect in workspace settings before analyzing dialect-specific
syntax. SQLGlot and bounded wrapper handling extract supported reads/writes, direct
usage and transformations. No database connection or SQL execution occurs.

Use **Lineage** for table dependencies, **Columns** for references and **Transformation
lineage** for output expressions. Select relationships to inspect exact statements.
Imported CREATE TABLE declarations support bounded wildcard expansion; absent schema,
ambiguous aliases and dynamic names retain diagnostics.

Some literal procedure/dynamic-SQL wrappers are supported, but arbitrary runtime
generation remains unresolved. See [SQL coverage](../SQL_PARSING.md) and
[transformation coverage](../TRANSFORMATION_LINEAGE.md).

Try [the SQL tutorial](../examples/sql.md). Optional [AI](../AI_ANALYSIS.md) is a separate
inferred workflow, not a requirement for large projects.
