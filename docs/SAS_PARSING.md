# SAS static analysis

The SAS parser is separate from SQLGlot. It groups semicolon-delimited DATA/PROC blocks,
preserves line locations, strips comments safely, resolves configured/static `%let` values,
and reports unsupported runtime constructs. PROC SQL statements use SQLGlot after SAS handling.

Tested: DATA outputs, SET/MERGE/UPDATE/MODIFY inputs, explicit INFILE/FILE paths, WORK assets,
PROC SQL CTAS, SORT OUT= (or in-place), SUMMARY/MEANS OUTPUT OUT=, TRANSPOSE, IMPORT DATAFILE/OUT,
EXPORT DATA/OUTFILE, common DATA/OUT procedure conventions and APPEND DATA/BASE.
PROC SQL SELECT expressions accept literal `FORMAT=` display modifiers (named, numeric,
character and custom formats ending in a period or decimal precision), before or after aliases,
and positive literal `LENGTH=` modifiers. `CALCULATED` references use uniquely defined SELECT
aliases without inventing base-table columns; missing or ambiguous aliases produce diagnostics.
SAS `DATETIME()` is recognized as an expression. Malformed modifiers remain parse errors.
These rules customize only the configured PROC SQL dialect instance; ordinary SQL is unchanged.
See the [SAS column modifier reference](https://support.sas.com/documentation/cdl/en/sqlproc/63043/HTML/default/n09x2o5dobk74an1mupf5f3y8emt.htm).

Parser cache version 9 invalidates earlier results on the next analysis. Run **Analyze all files**
in Lineage builder for previously analyzed workspaces; source bytes and original statement/line
evidence remain intact. Existing packaged executables/images need rebuilding for version 9.

## Static macro-variable expressions

`%LET` can combine already-known direct references with literal text, for example
`%let lib=raw; %let source=&lib..orders;`. Values resolve when assigned, so changing `lib`
later does not change `source`. References in double-quoted paths expand; single-quoted
paths remain literal. Original DATA/PROC code and line ranges retain the macro references.
See SAS's [macro-variable reference rules](https://support.sas.com/documentation/cdl/en/mcrolref/61885/HTML/default/a001071889.htm).

Unknown/indirect references, macro functions and oversized expansions remain unresolved.
An unresolved reassignment invalidates the previous variable value. Unmodeled macro calls,
conditional macro flow and CALL SYMPUT/SYMPUTX/EXECUTE invalidate known variable bindings
conservatively; a later explicit `%LET` can establish a fresh value. Configured values cannot
inject additional semicolon-delimited statements. Expansion is bounded to 1 MiB per statement.
This adds static variable expressions, not macro-definition invocation or a SAS interpreter.

Library mappings rewrite namespaces, not filesystem permissions. LIBNAME paths are not read.
One-level SAS datasets use WORK; WORK objects are temporary but remain in internal lineage.

Direct variables are conservative explicit KEEP/DROP/BY/RENAME lists and procedure VAR/ID/BY
where a single source establishes ownership. Multiple-source unqualified variable ownership
is not guessed. SAS ranges, arrays, automatic variable lists and arbitrary expressions do not
constitute a full compiled variable analysis. Consult source evidence for these constructs.

Macro definitions/invocations and conditional macro blocks are retained and diagnosed without
execution/expansion. Unresolved macro inputs suppress uncertain block edges. Name literals
outside the plain identifier rules are unresolved instead of tokenized into fabricated tables.
DATALINES/CARDS (including 4-semicolon forms) are data payloads and are never parsed as code.

Limitations: no SAS runtime, macro interpreter, PROC IML, general procedure output semantics,
dynamic libraries, automatic runtime session discovery or faithful execution order. Static WORK
datasets use workspace and explicitly configured job/folder scope. Configure supplied job IDs
in Parsing and lineage or use separate workspaces for unrelated sessions; absent that context,
independent jobs can remain ambiguous. Optional AI does not bypass evidence validation.

DATA/PROC evidence is sliced directly from the original source between statement offsets;
spacing, blank lines, comments and same-line block boundaries remain intact. Inline-data
contents remain evidence text without becoming executable statements or guessed dependencies.
