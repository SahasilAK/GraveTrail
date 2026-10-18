# Prompt repository

Lineage tasks use v1 GroundedResponse. Columns and code explanation use v2
ColumnResponse/ExplanationResponse; schemas are version-controlled under schemas/.
System instructions never contain interpolated source. User context is JSON. The prompt
hash includes system, template and exact response schema. AI records retain task, version,
source hash, validation outcome and usage. Full interactions remain opt-in.

Column suggestions must match a complete original parser operation and an unambiguous
explicit direct usage. Re-parsing an abbreviated quote is forbidden: it could omit a JOIN
or promote comments/string contents to code. Unknown wildcard coverage remains unresolved.
Explanation citations prove source location; natural-language meaning remains advisory.
Assets listed in explanations must participate in the complete cited operation. Neither
advisory task can merge table relationships, including legacy records during refresh.

Change prompt version, generated schemas and regression tests together.
