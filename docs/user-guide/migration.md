# Migrate to dbt on Databricks

Open **Engineering → Migration** to create a workspace project from retained sources. **Create
migration** on Analysis pins the latest committed analysis. **Migrate selection** on Lineage
starts from the selected asset and includes known upstream producers. **Create migration** in
Lineage Builder pins the current design and starts a scaffold.

Choose dbt and Databricks, confirm the target catalog and schema, and preview the migration.
Read admission, planned outputs and findings before creating the project. **Run static conversion**
creates a revision with model candidates. One source file can contribute several models.

## Source coverage

| Input | Initial conversion coverage |
| --- | --- |
| SQL | Candidates for single relational queries, CTAS, views and statically named SELECT INTO results. Generic and Databricks projections can satisfy static checks. Other dialects, schema-sensitive expressions, procedural code and mutations require additional work. |
| SAS | Candidates for simple PROC SQL and explicit single-input DATA step projections with scalar assignments and subsetting conditions. A simple IF/ELSE split gets separate model drafts with a warning about missing-value handling. Macros, row state, I/O and procedure options remain explicit obligations. |
| dbt | Compatible Databricks SQL models can keep their exact bytes. The converter preserves literal references, supported materializations and aliases, and basic source/model metadata. Unsupported configuration, external packages, versioned models, tests, snapshots, macros and Python resources need review before bringing them into the active project. |
| Builder | Snapshotted tables, columns and relationships. Supply grain, projections, filters and join intent before implementing a model. |

The ledger covers retained source offsets and records exclusions, missing outputs and opaque
regions. The original analysis and the independently extracted migrated lineage have separate
views. A dependency match cannot establish equivalence.

In **Schemas & mappings**, confirm input location and actual types. A known column with an
unknown type gets `STRING` metadata marked `assumed_string`. Wildcard outputs can have unknown
column names and unresolved layouts. The fallback adds neither SQL casts nor dbt contracts.

## Review and assistance

- Open **Review** to see the converted-code inventory, confidence tier, findings and open comments.
  Choose an artifact and a finding to locate the annotation in the numbered draft. The pinned
  original appears alongside it when expanded. Post a comment against an original source line,
  a generated SQL line or a whole section. Each comment keeps the revision it was written on.
- Define a conversion contract
  for unresolved outputs when authoring their behavior manually. Record scope exclusions and any
  processing that stays with the legacy system. To keep consuming a deliberately excluded
  transformation, record the externally supplied relation, confirmed columns and responsible owner,
  then review a patch that changes consumers to use the new source.
- Select one or more files in **AI assistance**. Preview the exact redacted disclosure, including
  optional upstream models, against a configured provider. External requests require the workspace
  to allow external requests and full source disclosure. Large scopes must be narrowed explicitly.
  With AI history disabled, unapplied replies and proposals are available in the current session.
  The request budget ledger and explicitly applied revisions are saved.
  In structured conversion requests, each selected model requires a SQL draft or an explicit
  unresolved result. The inspector and reviewed handoff still rely on the app's validation and
  engineer decisions.
- Review generated and manual edits as diffs. **Apply reviewed diff** updates the entire proposal
  atomically against its base revision. Schema and interface changes can invalidate downstream
  reviews. Restore an earlier converted revision from **Scope → Revision history**.
- Review each remaining semantic obligation to record engineer acceptance. This is separate from
  satisfying qualified static checks. Runtime equivalence stays unverified in both cases.
- In **Knowledge**, approve a lesson with evidence, conditions, an example and a counterexample.
  Project scope is the default. Workspace scope allows matching later projects to retrieve the
  lesson. Edits and chat messages never approve lessons. Revoke an outdated version to flag
  affected edits for review.

## Export and verify

**Draft bundle** includes annotated SQL candidates and comment-only drafts under `review/`.
Untranslated source sections are preserved as commented text under `review/sources/`, with line
numbers and source mappings. Draft bundles can contain original source excerpts. Models that depend
on blocked outputs stay outside the active tree. **Reviewed handoff** requires structurally valid
outputs and closure, with each semantic obligation checked or accepted. Both export modes include
source maps, checks, schema provenance, lineage and the external validation checklist. Optionally
include a mapping and type workbook or SVG/PNG lineage. The ZIP manifest hashes the packaged bytes.
Engineer-accepted models with remaining review findings have a companion annotated copy under
`review/`. The active model preserves the accepted SQL bytes.

The profile example contains environment-variable placeholders. The handoff targets
dbt Core 1.10.13 and dbt-databricks 1.10.13. GraveTrail performs conversion and static inspection
only. It never runs the model, a macro, SAS, dbt commands or warehouse queries. Use a separately
controlled environment to validate schemas, row counts, null behavior, duplicates and business
results, then plan operational cutover.

## Try a small migration

Import this SQL through **Sources**, analyze it, and choose **Create migration**.

```sql
create table accounts as select 1 as account_id;
create view account_ids as select account_id from accounts;
```

The preview should list two outputs. Run static conversion, inspect the generated `ref('accounts')`,
then export a reviewed handoff. The lineage should contain a single edge from `accounts` to
`account_ids` and the manifest should report `not_evaluated` for runtime equivalence.
