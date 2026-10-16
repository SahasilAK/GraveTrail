# SAS static analysis

The SAS parser is separate from SQLGlot. It groups semicolon-delimited DATA/PROC blocks,
preserves line locations, strips comments safely, resolves configured/static `%let` literals,
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

Parser cache version 8 invalidates earlier results on the next analysis. Run **Analyze all files**
in Lineage builder for previously analyzed workspaces; source bytes and original statement/line
evidence remain intact. Existing packaged executables/images need rebuilding to include this fix.

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
dynamic libraries, job scheduling/session boundaries or faithful execution order. Static WORK
datasets are workspace scoped and can be ambiguous across independent jobs. Add separate
workspaces for unrelated SAS sessions. Optional AI does not bypass evidence validation.

DATA/PROC evidence is sliced directly from the original source between statement offsets;
spacing, blank lines, comments and same-line block boundaries remain intact. Inline-data
contents remain evidence text without becoming executable statements or guessed dependencies.
