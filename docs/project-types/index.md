# Project types

| Source | Workflow | Tutorial | Detailed reference |
| --- | --- | --- | --- |
| SQL | [SQL](sql.md) | [SQL example](../examples/sql.md) | [SQL coverage](../SQL_PARSING.md) |
| SAS | [SAS](sas.md) | [SAS example](../examples/sas.md) | [SAS coverage](../SAS_PARSING.md) |
| dbt | [dbt](dbt.md) | [dbt example](../examples/dbt.md) | [Modes, resources and schemas](../DBT_SUPPORT.md) |

These inspect text/artifacts; they never execute SQL, SAS, dbt, Jinja, hooks or Python.
CSV can supply file/schema evidence where supported; matching a filename to a table
name does not create a dependency.
