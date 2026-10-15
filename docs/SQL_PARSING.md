# SQL parsing

SQLGlot is used as an AST parser; imported SQL is never sent to DuckDB for execution. Configure
an explicit dialect for vendor syntax or folder prefixes; generic SQL is the default. Parse
failures are diagnostics, never silently replaced by regex guesses or alternate dialects.

Supported tested operations: CTAS, CREATE VIEW/OR REPLACE, INSERT with UNION, UPDATE FROM,
MERGE USING, DELETE USING, SELECT, temporary tables, multiple statements, aliases, qualified
and quoted identifiers, CTEs, subqueries and correlated predicates. SQLGlot supports additional
dialect syntax, but tests define demonstrated coverage. Stored procedure/Command/Block logic
without safe AST extraction is explicitly unsupported. Dynamic SQL cannot be executed/resolved.

Only reachable CTE scopes contribute source assets/direct columns; unused CTEs are excluded.
CTEs and subqueries do not become persistent tables. Inner base-table column uses are counted;
outer CTE/derived-column uses are not counted again as transitive base references.
Qualified aliases bind within scopes, including supported correlated parents. Ambiguous
unqualified references are diagnosed. Wildcards are unknown instead of fabricated names.

Display names preserve spelling. Dotted quoted components retain their boundaries. Lookup
defaults to case-insensitive normalization; configure case sensitivity for your environment.
Unqualified cross-file matches link only to a unique qualified candidate and are inferred.

Statements retain the original snippet and original one-based line range. Semicolon splitting
honors comments, quoted strings, quoted identifiers and dollar strings. Procedural blocks with
internal statement syntax may remain unsupported rather than producing misleading evidence.

Current exclusions: database-catalog/schema discovery, full stored procedures, dynamic templating,
schema-driven wildcard expansion, arbitrary table-valued functions and runtime temporary-session
isolation. WORK/temporary identity is workspace scoped. Repeated writes expose possible static
dependencies; static code alone does not determine which write executed last.
