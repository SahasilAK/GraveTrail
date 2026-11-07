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
SAS `DATETIME()` traces to a runtime clock value. Malformed modifiers remain parse errors.
PROC SQL also recognizes adjacent literal date (`'01JAN2025'd`), time
(`'12:30:01't`) and datetime (`'01JAN2025:12:30:01'dt`) constants. These remain
literal syntax for dependency analysis; their SAS numeric values are not evaluated.
Invalid calendar/time values, unknown suffixes and two-digit-year leap-day constants
remain unsupported. This does not implement session `YEARCUTOFF` behavior. Original
typed-literal text and source coordinates remain evidence.
These rules customize only the configured PROC SQL dialect instance; ordinary SQL is unchanged.
See the [SAS column modifier reference](https://support.sas.com/documentation/cdl/en/sqlproc/63043/HTML/default/n09x2o5dobk74an1mupf5f3y8emt.htm).

Parser cache version 19 invalidates earlier results on the next analysis. Run **Analyze all files**
in Analysis for previously analyzed workspaces; source bytes and original statement/line
evidence remain intact.

## Column transformation subset

[Transformation lineage](TRANSFORMATION_LINEAGE.md) traces these static forms.

- A plain INPUT list with inline DATALINES or CARDS traces to the input statement and
  retained inline data. DATA-step assignments retain ordered variable versions.
- Simple filters retain row-selection inputs. Paired IF/ELSE assignments to the same
  variable distinguish the condition from the values it selects.
- Single-input SET and one concatenating SET can carry forward known columns through
  WORK datasets. Concatenation uses complete input layouts and traces each variable only
  to inputs that supply it. Simple IN= indicators track dataset membership.
- Simple PROC SORT copies values through to its output. BY keys supply ordering context
  or row-selection context for NODUPKEY. Bounded NWAY SUMMARY/MEANS sums and grouped
  PROC RANK expose their value and grouping inputs.
- PROC SQL follows named CALCULATED aliases, simple correlated predicates and derived
  tables. It retains explicit column positions for literal INSERT VALUES.

Unknown layouts, match merges, repeated SET statements, complex retention, arrays, loops,
multi-output control flow, and unexpanded macros remain coverage gaps. No SAS code executes.
[SAS guide to combining data](https://documentation.sas.com/api/collections/pgmsascdc/v_007/docsets/lepg/content/lepg.pdf?locale=en)

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
